from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Any, Callable

from doc_translator.babeldoc_hooks import BabeldocHookContext
from doc_translator.settings_service import RuntimeSettings


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BabeldocLibraryResult:
    mono_output: Path
    hook_sidecar: Path | None


def translate_pdf_with_babeldoc_library(
    input_path: Path,
    output_dir: Path,
    working_dir: Path,
    runtime: RuntimeSettings,
    *,
    source_language: str | None,
    target_language: str,
    use_ocr_workaround: bool,
    qps: int,
    report_interval: float,
    on_progress_event: Callable[[dict[str, Any]], None] | None = None,
) -> BabeldocLibraryResult:
    from babeldoc.docvision.doclayout import DocLayoutModel
    from babeldoc.format.pdf import high_level
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.format.pdf.translation_config import WatermarkOutputMode
    from babeldoc.translator.translator import OpenAITranslator
    from babeldoc.translator.translator import set_translate_rate_limiter
    import httpx
    import openai

    hook_context = BabeldocHookContext()
    set_translate_rate_limiter(qps)

    translator = OpenAITranslator(
        lang_in=source_language or "en",
        lang_out=target_language,
        model=runtime.model_name,
        base_url=runtime.model_base_url,
        api_key=runtime.model_api_key,
    )
    translator.client = openai.OpenAI(
        base_url=runtime.model_base_url,
        api_key=runtime.model_api_key,
        http_client=httpx.Client(
            limits=httpx.Limits(max_connections=None, max_keepalive_connections=None),
            timeout=runtime.model_timeout_seconds,
        ),
    )
    doc_layout_model = DocLayoutModel.load_onnx()
    config = TranslationConfig(
        input_file=str(input_path),
        font=None,
        pages=None,
        output_dir=str(output_dir),
        translator=translator,
        term_extraction_translator=translator,
        debug=False,
        lang_in=source_language or "en",
        lang_out=target_language,
        no_dual=True,
        no_mono=False,
        qps=qps,
        split_short_lines=False,
        short_line_split_factor=0.8,
        doc_layout_model=doc_layout_model,
        skip_clean=False,
        dual_translate_first=False,
        disable_rich_text_translate=False,
        enhance_compatibility=False,
        use_alternating_pages_dual=False,
        report_interval=report_interval,
        min_text_length=5,
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        table_model=None,
        show_char_box=False,
        skip_scanned_detection=use_ocr_workaround,
        ocr_workaround=use_ocr_workaround,
        working_dir=str(working_dir),
        pool_max_workers=qps,
        auto_extract_glossary=True,
        auto_enable_ocr_workaround=False,
        enable_graphic_element_process=True,
        merge_alternating_line_numbers=True,
        skip_translation=False,
        skip_form_render=False,
        skip_curve_render=False,
        only_parse_generate_pdf=False,
        remove_non_formula_lines=False,
    )
    hook_context.set_working_dir(Path(config.working_dir))
    hook_context.set_target_language(target_language)

    def nop(_config: TranslationConfig) -> None:
        return None

    getattr(doc_layout_model, "init_font_mapper", nop)(config)

    logger.info(
        "Starting BabelDOC library translation",
        extra={
            "input_path": str(input_path),
            "timeout_seconds": runtime.model_timeout_seconds,
            "qps": qps,
        },
    )
    hooked_high_level = _build_hooked_high_level(high_level, hook_context)
    try:
        translate_result = asyncio.run(_run_babeldoc_translation(hooked_high_level, config, on_progress_event))
    finally:
        try:
            hook_sidecar = hook_context.write_sidecar()
        except OSError:
            logger.exception("Failed to write BabelDOC hook sidecar")
            hook_sidecar = None

    mono_output = _mono_output_from_result(translate_result, output_dir, input_path.stem)
    return BabeldocLibraryResult(mono_output=mono_output, hook_sidecar=hook_sidecar)


async def _run_babeldoc_translation(
    high_level: Any,
    config: Any,
    on_progress_event: Callable[[dict[str, Any]], None] | None,
) -> Any:
    translate_result = None
    try:
        async for event in high_level.async_translate(config):
            event_type = event.get("type")
            if on_progress_event is not None:
                on_progress_event(_jsonable_progress_event(event))
            if event_type == "error":
                raise RuntimeError(f"BabelDOC translation failed: {event.get('error')}")
            if event_type == "finish":
                translate_result = event.get("translate_result")
                break
    except Exception:
        config.cancel_translation()
        raise
    if translate_result is None:
        raise RuntimeError("BabelDOC finished without a translation result")
    return translate_result


def _build_hooked_high_level(high_level: Any, hook_context: BabeldocHookContext) -> Any:
    originals = {
        "ParagraphFinder": high_level.ParagraphFinder,
        "StylesAndFormulas": high_level.StylesAndFormulas,
        "ILTranslator": high_level.ILTranslator,
        "ILTranslatorLLMOnly": high_level.ILTranslatorLLMOnly,
        "Typesetting": high_level.Typesetting,
        "PDFCreater": high_level.PDFCreater,
    }

    class HookedParagraphFinder(originals["ParagraphFinder"]):
        def process(self, document: Any) -> Any:
            result = super().process(document)
            hook_context.note_phase("paragraph_finder")
            return result

    class HookedStylesAndFormulas(originals["StylesAndFormulas"]):
        def process(self, document: Any) -> Any:
            result = super().process(document)
            hook_context.classify_document(document)
            if hook_context.merge_same_line_fragments_before_translation(document):
                hook_context.classify_document(document)
            return result

    class HookedILTranslator(originals["ILTranslator"]):
        def pre_translate_paragraph(self, paragraph: Any, tracker: Any, page_font_map: Any, xobj_font_map: Any) -> Any:
            if hook_context.should_skip_translation(paragraph):
                return None, None
            text, translate_input = self._pre_translate_paragraph(
                paragraph,
                tracker,
                page_font_map,
                xobj_font_map,
                force_plain_text=hook_context.should_force_plain_text(paragraph),
            )
            if text is None:
                return None, None
            return hook_context.translation_text_override(paragraph, text), translate_input

        def _pre_translate_paragraph(
            self,
            paragraph: Any,
            tracker: Any,
            page_font_map: Any,
            xobj_font_map: Any,
            *,
            force_plain_text: bool = False,
            allow_short: bool = False,
        ) -> Any:
            vertical = bool(getattr(paragraph, "vertical", False))
            if vertical and not force_plain_text:
                return None, None
            if vertical:
                paragraph.vertical = False
            try:
                tracker.set_pdf_unicode(paragraph.unicode)
                if paragraph.xobj_id in xobj_font_map:
                    page_font_map = xobj_font_map[paragraph.xobj_id]
                disable_rich_text = force_plain_text
                if not self.support_llm_translate:
                    disable_rich_text = True

                translate_input = self.get_translate_input(paragraph, page_font_map, disable_rich_text)
                if not translate_input:
                    return None, None
                tracker.set_input(translate_input.unicode)
                tracker.set_placeholders(translate_input.placeholders)
                tracker.set_original_placeholders(getattr(translate_input, "original_placeholder_tokens", None))
                text = translate_input.unicode
                if not allow_short and len(text) < self.translation_config.min_text_length:
                    logger.debug(
                        "Text too short to translate, skip. Text: %s. Paragraph id: %s.",
                        text,
                        paragraph.debug_id,
                    )
                    return None, None
                return text, translate_input
            finally:
                if vertical:
                    paragraph.vertical = True

        def post_translate_paragraph(self, paragraph: Any, tracker: Any, translate_input: Any, translated_text: str) -> Any:
            translated_text = hook_context.translated_text_override(paragraph, translate_input, translated_text)
            result = super().post_translate_paragraph(paragraph, tracker, translate_input, translated_text)
            hook_context.record_translation(paragraph)
            return result

        def translate(self, docs: Any) -> Any:
            result = super().translate(docs)
            hook_context.reconcile_translation()
            return result

    class HookedILTranslatorLLMOnly(originals["ILTranslatorLLMOnly"]):
        def __init__(self, translate_engine: Any, translation_config: Any, tokenizer: Any = None) -> None:
            super().__init__(translate_engine, translation_config, tokenizer)
            self.il_translator = HookedILTranslator(
                translate_engine=translate_engine,
                translation_config=translation_config,
                tokenizer=self.tokenizer,
            )
            self.il_translator.use_as_fallback = True

        def translate(self, docs: Any) -> Any:
            result = super().translate(docs)
            hook_context.reconcile_translation()
            return result

    class HookedTypesetting(originals["Typesetting"]):
        def typesetting_document(self, document: Any) -> Any:
            hook_context.reconcile_translation()
            hook_context.split_numbered_lists_before_typesetting(document)
            hook_context.restore_source_layouts_before_typesetting(document)
            hook_context.note_phase("typesetting")
            return super().typesetting_document(document)

    class HookedPDFCreater(originals["PDFCreater"]):
        def create_render_units_for_page(self, page: Any, translation_config: Any) -> Any:
            render_units = super().create_render_units_for_page(page, translation_config)
            return hook_context.replace_axis_label_render_units(page, render_units, translation_config)

    globals_copy = dict(high_level.async_translate.__globals__)
    globals_copy.update(
        {
            "ParagraphFinder": HookedParagraphFinder,
            "StylesAndFormulas": HookedStylesAndFormulas,
            "ILTranslator": HookedILTranslator,
            "ILTranslatorLLMOnly": HookedILTranslatorLLMOnly,
            "Typesetting": HookedTypesetting,
            "PDFCreater": HookedPDFCreater,
        }
    )
    globals_copy["_do_translate_single"] = _clone_function_with_globals(high_level._do_translate_single, globals_copy)
    globals_copy["do_translate"] = _clone_function_with_globals(high_level.do_translate, globals_copy)
    globals_copy["get_translation_stage"] = _clone_function_with_globals(high_level.get_translation_stage, globals_copy)
    globals_copy["async_translate"] = _clone_function_with_globals(high_level.async_translate, globals_copy)
    return SimpleNamespace(async_translate=globals_copy["async_translate"])


def _clone_function_with_globals(function: Any, globals_copy: dict[str, Any]) -> Any:
    cloned = FunctionType(
        function.__code__,
        globals_copy,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    cloned.__kwdefaults__ = function.__kwdefaults__
    cloned.__annotations__ = dict(getattr(function, "__annotations__", {}))
    return cloned


def _jsonable_progress_event(event: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in event.items():
        if key == "translate_result":
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            payload[key] = value
        else:
            payload[key] = str(value)
    return payload


def _mono_output_from_result(translate_result: Any, output_dir: Path, input_stem: str) -> Path:
    for attr in ("no_watermark_mono_pdf_path", "mono_pdf_path"):
        candidate = getattr(translate_result, attr, None)
        if candidate:
            path = Path(candidate)
            if path.exists():
                return path
    matches = sorted(output_dir.glob(f"{input_stem}*.mono.pdf")) or sorted(output_dir.glob("*.mono.pdf"))
    if not matches:
        raise RuntimeError("BabelDOC finished without producing a monolingual PDF output")
    return max(matches, key=lambda candidate: candidate.stat().st_mtime)
