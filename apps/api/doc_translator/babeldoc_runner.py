from __future__ import annotations

import asyncio
import copy
import logging
import statistics
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Any, Callable

from doc_translator.babeldoc_hooks import BabeldocHookContext
from doc_translator.babeldoc_translator import BabeldocModelTranslator
from doc_translator.hook_policy import HookPolicy
from doc_translator.settings_service import RuntimeSettings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _HardLineBreakTypesettingUnit:
    font_size: float | None = None
    debug_info: bool = False

    char: Any = None
    formular: Any = None
    unicode: str = "\n"
    width: float = 0.0
    height: float = 0.0
    is_space: bool = False
    is_cjk_char: bool = False
    mixed_character_blacklist: bool = False
    is_hung_punctuation: bool = False
    is_cannot_appear_in_line_end_punctuation: bool = False
    can_break_line: bool = True
    can_passthrough: bool = False

    def try_get_unicode(self) -> str:
        return "\n"

    def relocate(self, _x: float, _y: float, _scale: float) -> "_HardLineBreakTypesettingUnit":
        return self

    def render(self) -> tuple[list[Any], list[Any], list[Any]]:
        return [], [], []


def _is_hard_line_break_unit(unit: Any) -> bool:
    return isinstance(unit, _HardLineBreakTypesettingUnit)


@dataclass(frozen=True, slots=True)
class BabeldocLibraryResult:
    mono_output: Path
    hook_sidecar: Path | None
    structure_before: Path | None
    structure_after: Path | None


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
    from babeldoc.translator.translator import set_translate_rate_limiter

    hook_context = BabeldocHookContext(hook_policy=HookPolicy.from_env())
    set_translate_rate_limiter(qps)

    translator = BabeldocModelTranslator(
        runtime,
        lang_in=source_language or "en",
        lang_out=target_language,
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
        translator.close()
        try:
            hook_sidecar = hook_context.write_sidecar()
        except OSError:
            logger.exception("Failed to write BabelDOC hook sidecar")
            hook_sidecar = None
        try:
            structure_before = hook_context.write_structure_snapshot("before_translation")
            structure_after = hook_context.write_structure_snapshot("after_translation")
        except OSError:
            logger.exception("Failed to write BabelDOC structure snapshots")
            structure_before = None
            structure_after = None

    mono_output = _mono_output_from_result(translate_result, output_dir, input_path.stem)
    return BabeldocLibraryResult(
        mono_output=mono_output,
        hook_sidecar=hook_sidecar,
        structure_before=structure_before,
        structure_after=structure_after,
    )


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
        "typesetting_module": sys.modules[high_level.Typesetting.__module__],
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
            hook_context.normalize_font_traits(document)
            hook_context.classify_document(document)
            if hook_context.normalize_fragmented_paragraphs_before_translation(document):
                hook_context.classify_document(document)
                hook_context.note_phase("normalize_fragmented_paragraphs_before_translation")
            if hook_context.merge_same_line_fragment_bridges_before_translation(document):
                hook_context.classify_document(document)
                hook_context.note_phase("merge_same_line_fragment_bridges_before_translation")
            if hook_context.merge_contiguous_body_lines_before_translation(document):
                hook_context.classify_document(document)
                hook_context.note_phase("merge_contiguous_body_lines_before_translation")
            if hook_context.split_wrapped_same_line_tails_before_translation(document):
                hook_context.classify_document(document)
                hook_context.note_phase("split_wrapped_same_line_tails_before_translation")
                if hook_context.merge_same_line_fragment_bridges_before_translation(document):
                    hook_context.classify_document(document)
                    hook_context.note_phase("merge_same_line_fragment_bridges_after_wrapped_tail_split")
                if hook_context.merge_contiguous_body_lines_before_translation(document):
                    hook_context.classify_document(document)
                    hook_context.note_phase("merge_contiguous_body_lines_after_wrapped_tail_split")
            if hook_context.merge_same_line_fragments_before_translation(document):
                hook_context.classify_document(document)
            if hook_context.remove_subsumed_same_line_duplicates_before_translation(document):
                hook_context.classify_document(document)
                hook_context.note_phase("remove_subsumed_same_line_duplicates_before_translation")
            if hook_context.collapse_overlapping_same_baseline_fragments_before_translation(document):
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
            )
            if text is None:
                return None, None
            return hook_context.translation_text_override(paragraph, text, translate_input), translate_input

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
            source_composition = copy.deepcopy(getattr(paragraph, "pdf_paragraph_composition", []) or [])
            translated_text = hook_context.translated_text_override(paragraph, translate_input, translated_text)
            result = super().post_translate_paragraph(paragraph, tracker, translate_input, translated_text)
            hook_context.restore_definition_line_styles_after_translation(paragraph, translated_text, source_composition)
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

        def _build_llm_prompt(
            self,
            json_input_str: str,
            title_paragraph: Any | None,
            local_title_paragraph: Any | None,
            batch_text_for_glossary_matching: str,
        ) -> str:
            prompt = super()._build_llm_prompt(
                json_input_str=json_input_str,
                title_paragraph=title_paragraph,
                local_title_paragraph=local_title_paragraph,
                batch_text_for_glossary_matching=batch_text_for_glossary_matching,
            )
            return _strengthen_llm_slice_boundary_prompt(prompt)

        def translate(self, docs: Any) -> Any:
            result = super().translate(docs)
            hook_context.reconcile_translation()
            return result

    class HookedTypesetting(originals["Typesetting"]):
        def create_typesetting_units(self, paragraph: Any, fonts: dict[str, Any]) -> list[Any]:
            if "\n" not in str(getattr(paragraph, "unicode", "") or ""):
                return super().create_typesetting_units(paragraph, fonts)
            if not getattr(paragraph, "pdf_paragraph_composition", None):
                return []
            result = []

            @cache
            def get_font(font_id: str, xobj_id: int | None) -> Any:
                if xobj_id in fonts:
                    return fonts[xobj_id][font_id]
                return fonts[font_id]

            for composition in paragraph.pdf_paragraph_composition:
                if composition is None:
                    continue
                if composition.pdf_line:
                    result.extend(
                        [
                            originals["typesetting_module"].TypesettingUnit(char=char)
                            for char in composition.pdf_line.pdf_character
                        ],
                    )
                elif composition.pdf_character:
                    result.append(
                        originals["typesetting_module"].TypesettingUnit(
                            char=composition.pdf_character,
                            debug_info=paragraph.debug_info,
                        ),
                    )
                elif composition.pdf_same_style_characters:
                    result.extend(
                        [
                            originals["typesetting_module"].TypesettingUnit(char=char)
                            for char in composition.pdf_same_style_characters.pdf_character
                        ],
                    )
                elif composition.pdf_same_style_unicode_characters:
                    same_style_unicode = composition.pdf_same_style_unicode_characters
                    style = same_style_unicode.pdf_style
                    if style is None:
                        logger.warning("Style is None while preserving hard line breaks.")
                        continue
                    font_id = style.font_id
                    if font_id is None:
                        logger.warning("Font ID is None while preserving hard line breaks.")
                        continue
                    font = get_font(font_id, paragraph.xobj_id)
                    for char_unicode in str(same_style_unicode.unicode or ""):
                        if char_unicode == "\n":
                            result.append(
                                _HardLineBreakTypesettingUnit(
                                    font_size=style.font_size,
                                    debug_info=same_style_unicode.debug_info or False,
                                )
                            )
                            continue
                        result.append(
                            originals["typesetting_module"].TypesettingUnit(
                                unicode=char_unicode,
                                font=self.font_mapper.map(font, char_unicode),
                                original_font=font,
                                font_size=style.font_size,
                                style=style,
                                xobj_id=paragraph.xobj_id,
                                debug_info=same_style_unicode.debug_info or False,
                            )
                        )
                elif composition.pdf_formula:
                    result.extend([originals["typesetting_module"].TypesettingUnit(formular=composition.pdf_formula)])
                else:
                    logger.error(
                        "Unknown composition type while preserving hard line breaks. "
                        "Composition: %s. Paragraph: %s.",
                        composition,
                        paragraph,
                    )
                    continue
            return list(
                filter(
                    lambda unit: _is_hard_line_break_unit(unit) or unit.unicode is None or unit.font is not None,
                    result,
                ),
            )

        def _get_width_before_next_break_point(self, typesetting_units: list[Any], scale: float) -> float:
            if not typesetting_units or _is_hard_line_break_unit(typesetting_units[0]):
                return 0
            total_width = 0.0
            for unit in typesetting_units:
                if _is_hard_line_break_unit(unit) or unit.can_break_line:
                    return total_width * scale
                total_width += unit.width
            return total_width * scale

        def _layout_typesetting_units(
            self,
            typesetting_units: list[Any],
            box: Any,
            scale: float,
            line_skip: float,
            paragraph: Any,
            use_english_line_break: bool = True,
        ) -> tuple[list[Any], bool]:
            if not any(_is_hard_line_break_unit(unit) for unit in typesetting_units):
                return super()._layout_typesetting_units(typesetting_units, box, scale, line_skip, paragraph, use_english_line_break)

            font_sizes = []
            for unit in typesetting_units:
                if _is_hard_line_break_unit(unit):
                    continue
                if unit.font_size:
                    font_sizes.append(unit.font_size)
                if unit.char and unit.char.pdf_style and unit.char.pdf_style.font_size:
                    font_sizes.append(unit.char.pdf_style.font_size)
            font_sizes.sort()
            font_size = statistics.mode(font_sizes)

            space_width = self.font_mapper.base_font.char_lengths("你", font_size * scale)[0] * 0.5
            unit_heights = [unit.height for unit in typesetting_units if not _is_hard_line_break_unit(unit)]
            if not unit_heights:
                avg_height = 0
            elif len(unit_heights) == 1:
                avg_height = unit_heights[0] * scale
            else:
                try:
                    avg_height = statistics.mode(unit_heights) * scale
                except statistics.StatisticsError:
                    avg_height = sum(unit_heights) / len(unit_heights) * scale

            current_x = box.x
            current_y = box.y2 - avg_height
            box = copy.deepcopy(box)
            line_height = 0.0
            current_line_heights = []
            typeset_units = []
            all_units_fit = True
            last_unit = None
            if paragraph.first_line_indent:
                current_x += space_width * 4

            def break_line() -> bool:
                nonlocal current_x, current_y, line_height, current_line_heights, all_units_fit, last_unit
                current_x = box.x
                if not current_line_heights:
                    line_step = avg_height * line_skip if avg_height else 0
                else:
                    max_height = max(current_line_heights)
                    mode_height = statistics.mode(current_line_heights)
                    line_step = max(mode_height * line_skip, max_height * 1.05)
                current_y -= line_step
                line_height = 0.0
                current_line_heights = []
                last_unit = None
                if current_y < box.y:
                    all_units_fit = False
                return line_step > 0

            for i, unit in enumerate(typesetting_units):
                if _is_hard_line_break_unit(unit):
                    if not break_line():
                        return [], False
                    continue

                unit_width = unit.width * scale
                unit_height = unit.height * scale

                if current_x == box.x and unit.is_space:
                    continue

                if (
                    last_unit
                    and last_unit.is_cjk_char ^ unit.is_cjk_char
                    and (
                        last_unit.box
                        and last_unit.box.y
                        and current_y - 0.1
                        <= last_unit.box.y2
                        <= current_y + line_height + 0.1
                    )
                    and not last_unit.mixed_character_blacklist
                    and not unit.mixed_character_blacklist
                    and current_x > box.x
                    and unit.try_get_unicode() != " "
                    and last_unit.try_get_unicode() != " "
                    and last_unit.try_get_unicode() not in ["。", "！", "？", "；", "：", "，"]
                ):
                    current_x += space_width * 0.5
                if use_english_line_break:
                    width_before_next_break_point = self._get_width_before_next_break_point(typesetting_units[i:], scale)
                else:
                    width_before_next_break_point = 0

                if not unit.is_hung_punctuation and (
                    (current_x + unit_width > box.x2)
                    or (
                        use_english_line_break
                        and current_x + unit_width + width_before_next_break_point > box.x2
                    )
                    or (
                        unit.is_cannot_appear_in_line_end_punctuation
                        and current_x + unit_width * 2 > box.x2
                    )
                ):
                    current_x = box.x
                    if not current_line_heights:
                        return [], False
                    max_height = max(current_line_heights)
                    mode_height = statistics.mode(current_line_heights)
                    current_y -= max(mode_height * line_skip, max_height * 1.05)
                    line_height = 0.0
                    current_line_heights = []
                    last_unit = None
                    if current_y < box.y:
                        all_units_fit = False
                    if unit.is_space:
                        line_height = max(line_height, unit_height)
                        continue

                relocated_unit = unit.relocate(current_x, current_y, scale)
                typeset_units.append(relocated_unit)

                if not unit.is_space:
                    current_line_heights.append(unit_height)

                prev_x = current_x
                current_x = relocated_unit.box.x2
                if prev_x > current_x:
                    logger.warning("Coordinates wrapped around. TypesettingUnit: %s.", unit.box)

                last_unit = relocated_unit

            return typeset_units, all_units_fit

        def render_page(self, page: Any) -> None:
            hook_context.normalize_body_scales_before_render(page)
            return super().render_page(page)

        def typesetting_document(self, document: Any) -> Any:
            hook_context.reconcile_translation()
            hook_context.split_numbered_lists_before_typesetting(document)
            hook_context.restore_source_layouts_before_typesetting(document)
            hook_context.normalize_body_font_sizes_before_typesetting(document)
            hook_context.capture_after_translation_snapshot(document)
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


def _strengthen_llm_slice_boundary_prompt(prompt: str) -> str:
    marker = "2. Input paragraphs may be **sliced pieces of the same original paragraph**."
    if marker not in prompt or "Do NOT complete missing sentence parts" in prompt:
        return prompt
    extra_rules = (
        "\n   - Translate only the words that appear inside that paragraph's own input.\n"
        "   - Do NOT complete missing sentence parts from neighboring inputs or contextual hints.\n"
        "   - If an input starts or ends mid-sentence, keep the translation fragment incomplete in the same way.\n"
        "   - Adjacent inputs are context for terminology only, not content you may copy into this output."
    )
    return prompt.replace(marker, f"{marker}{extra_rules}", 1)


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
