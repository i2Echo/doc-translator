from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import fitz
import httpx
import pytesseract
from docx import Document
from PIL import Image
from sqlalchemy.orm import Session, selectinload

from doc_translator.audit import record_audit
from doc_translator.db import SessionLocal
from doc_translator.models import JobEvent, JobFile, JobFileKind, JobStatus, TranslationJob
from doc_translator.settings_service import RuntimeSettings, get_runtime_settings
from doc_translator.storage import build_output_target, file_checksum


logger = logging.getLogger(__name__)

BABELDOC_LANGUAGE_CODES = {
    "auto": None,
    "auto detect": None,
    "en": "en",
    "english": "en",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "chinese": "zh-CN",
    "ja": "ja",
    "japanese": "ja",
    "es": "es",
    "spanish": "es",
    "fr": "fr",
    "french": "fr",
    "de": "de",
    "german": "de",
}
PDF_OCR_DPI = 300
PDF_BACKGROUND_ANALYSIS_DPI = 24
PDF_OCR_WORKAROUND_MIN_LUMINANCE = 235.0
PDF_OCR_WORKAROUND_MIN_BRIGHT_RATIO = 0.6
PDF_OCR_WORKAROUND_PAGE_SAMPLE_LIMIT = 5


class JobCancelledError(Exception):
    pass


class OpenAICompatibleTranslator:
    def __init__(self, runtime: RuntimeSettings) -> None:
        self.runtime = runtime
        base_url = runtime.model_base_url.rstrip("/")
        self.endpoint = f"{base_url}/chat/completions"

    def translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        preserve_line_breaks: bool = True,
    ) -> str:
        if not text.strip():
            return text
        formatting_instruction = (
            "Preserve line breaks and lists."
            if preserve_line_breaks
            else "Preserve paragraph breaks and lists, but reflow ordinary line breaks naturally for the target language."
        )
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.runtime.model_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.runtime.model_name,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Translate the user's text from {source_language} to {target_language}. "
                            f"Return only the translated text. {formatting_instruction} "
                            "Keep citations, numbers, and inline Latin-script terms accurately formatted."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            },
            timeout=self.runtime.model_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model API returned an unexpected response") from exc

    def test_connection(self) -> tuple[int, str]:
        started = datetime.now(timezone.utc)
        preview = self.translate_text("hello", "English", "Spanish")
        latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return latency, preview[:120]


def add_job_event(session: Session, job: TranslationJob, message: str, *, level: str = "info", details: dict | None = None) -> None:
    session.add(JobEvent(job_id=job.id, level=level, message=message, details=details))


def update_job_state(
    session: Session,
    job: TranslationJob,
    *,
    status: JobStatus | None = None,
    progress: int | None = None,
    error_message: str | None = None,
    message: str | None = None,
    details: dict | None = None,
) -> None:
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if error_message is not None:
        job.error_message = error_message
    if status == JobStatus.PARSING and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        job.completed_at = datetime.now(timezone.utc)
    if message:
        add_job_event(session, job, message, level="error" if status == JobStatus.FAILED else "info", details=details)
    session.commit()


def ensure_not_cancelled(session: Session, job: TranslationJob) -> None:
    session.refresh(job)
    if job.cancel_requested or job.status == JobStatus.CANCELLED:
        raise JobCancelledError("Job was cancelled")


def split_text(text: str, max_chars: int = 1800) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current = ""
    for paragraph in text.splitlines(keepends=True):
        if len(current) + len(paragraph) > max_chars and current:
            parts.append(current)
            current = paragraph
        else:
            current += paragraph
    if current:
        parts.append(current)
    return parts


def translate_segments(
    translator: OpenAICompatibleTranslator,
    segments: list[str],
    *,
    source_language: str,
    target_language: str,
    preserve_line_breaks: bool,
    on_progress: Callable[[int, int], None],
    cancel_check: Callable[[], None],
) -> list[str]:
    translated: list[str] = []
    total = len(segments)
    for index, segment in enumerate(segments, start=1):
        cancel_check()
        chunked = split_text(segment)
        translated_chunks = [
            translator.translate_text(
                chunk,
                source_language=source_language,
                target_language=target_language,
                preserve_line_breaks=preserve_line_breaks,
            )
            for chunk in chunked
        ]
        translated.append("".join(translated_chunks))
        on_progress(index, total)
    return translated


def _pixmap_to_image(pixmap: fitz.Pixmap) -> Image.Image:
    mode = "RGBA" if pixmap.alpha else "RGB"
    return Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)


def _normalize_language(language: str) -> str:
    return language.strip().lower()


def _babeldoc_language_code(language: str, *, allow_auto: bool) -> str | None:
    normalized = _normalize_language(language)
    code = BABELDOC_LANGUAGE_CODES.get(normalized)
    if normalized not in BABELDOC_LANGUAGE_CODES:
        supported = "English, Chinese, Japanese, Spanish, French, German"
        raise RuntimeError(f"Unsupported PDF language '{language}'. Supported values: {supported}")
    if code is None:
        if allow_auto:
            return None
        raise RuntimeError("PDF target language must be explicitly selected")
    return code


def _page_has_extractable_text(page: fitz.Page) -> bool:
    return bool(page.get_text("words"))


def _ocr_language(runtime: RuntimeSettings) -> str | None:
    return None if runtime.ocr_language_hint == "auto" else runtime.ocr_language_hint


def _has_codepoint_in_ranges(text: str, ranges: tuple[tuple[str, str], ...]) -> bool:
    return any(start <= char <= end for char in text for start, end in ranges)


def _select_pdf_font(text: str) -> str:
    if _has_codepoint_in_ranges(text, (("\uac00", "\ud7af"), ("\u1100", "\u11ff"), ("\u3130", "\u318f"))):
        return "korea"
    if _has_codepoint_in_ranges(text, (("\u3040", "\u30ff"), ("\u31f0", "\u31ff"))):
        return "japan"
    if _has_codepoint_in_ranges(
        text,
        (
            ("\u3400", "\u4dbf"),
            ("\u4e00", "\u9fff"),
            ("\uf900", "\ufaff"),
            ("\uff00", "\uffef"),
            ("\u0400", "\u04ff"),
        ),
    ):
        return "china-s"
    return "helv"


def _insert_background_text_best_fit(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
) -> None:
    if not text.strip():
        return

    font_name = _select_pdf_font(text)
    initial_font_size = max(6.0, min(rect.height * 0.9, 22.0))
    font_sizes = [initial_font_size, max(initial_font_size - 1, 6.0), max(initial_font_size - 2, 6.0), 6.0]
    tried_sizes: set[float] = set()
    for font_size in font_sizes:
        rounded_size = round(font_size, 2)
        if rounded_size in tried_sizes:
            continue
        tried_sizes.add(rounded_size)
        remainder = page.insert_textbox(
            rect,
            text,
            fontsize=rounded_size,
            fontname=font_name,
            overlay=False,
        )
        if remainder >= 0:
            return

    page.insert_text(
        rect.bottom_left,
        text,
        fontsize=6,
        fontname=font_name,
        overlay=False,
    )


def _ocr_page_lines(page: fitz.Page, runtime: RuntimeSettings) -> list[tuple[fitz.Rect, str]]:
    pixmap = page.get_pixmap(dpi=PDF_OCR_DPI, alpha=False)
    image = _pixmap_to_image(pixmap)
    language = _ocr_language(runtime)
    if language:
        data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
    else:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    line_map: dict[tuple[int, int, int], dict[str, float | list[str]]] = {}
    scale_x = page.rect.width / pixmap.width
    scale_y = page.rect.height / pixmap.height

    for index, raw_text in enumerate(data["text"]):
        text = raw_text.strip()
        if not text:
            continue

        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        left = float(data["left"][index]) * scale_x
        top = float(data["top"][index]) * scale_y
        width = float(data["width"][index]) * scale_x
        height = float(data["height"][index]) * scale_y
        right = left + width
        bottom = top + height

        existing = line_map.get(key)
        if existing is None:
            line_map[key] = {"left": left, "top": top, "right": right, "bottom": bottom, "words": [text]}
            continue

        existing["left"] = min(existing["left"], left)
        existing["top"] = min(existing["top"], top)
        existing["right"] = max(existing["right"], right)
        existing["bottom"] = max(existing["bottom"], bottom)
        existing["words"].append(text)

    lines: list[tuple[fitz.Rect, str]] = []
    for key in sorted(line_map):
        line = line_map[key]
        rect = fitz.Rect(line["left"], line["top"], line["right"], line["bottom"])
        text = " ".join(line["words"])
        lines.append((rect, text))
    return lines


def _pdf_has_any_extractable_text(path: Path) -> bool:
    document = fitz.open(path)
    try:
        return any(_page_has_extractable_text(page) for page in document)
    finally:
        document.close()


def _page_luminance_metrics(page: fitz.Page) -> tuple[float, float]:
    pixmap = page.get_pixmap(dpi=PDF_BACKGROUND_ANALYSIS_DPI, alpha=False)
    samples = pixmap.samples
    pixel_count = len(samples) // 3
    if pixel_count == 0:
        return 0.0, 0.0

    total_luminance = 0.0
    bright_pixels = 0
    for index in range(0, len(samples), 3):
        red = samples[index]
        green = samples[index + 1]
        blue = samples[index + 2]
        luminance = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
        total_luminance += luminance
        if luminance >= 245:
            bright_pixels += 1

    return total_luminance / pixel_count, bright_pixels / pixel_count


def _pdf_prefers_ocr_workaround(path: Path) -> bool:
    document = fitz.open(path)
    try:
        sample_count = min(document.page_count, PDF_OCR_WORKAROUND_PAGE_SAMPLE_LIMIT)
        if sample_count == 0:
            return False

        total_luminance = 0.0
        total_bright_ratio = 0.0
        for page_index in range(sample_count):
            luminance, bright_ratio = _page_luminance_metrics(document[page_index])
            total_luminance += luminance
            total_bright_ratio += bright_ratio

        average_luminance = total_luminance / sample_count
        average_bright_ratio = total_bright_ratio / sample_count
        return (
            average_luminance >= PDF_OCR_WORKAROUND_MIN_LUMINANCE
            and average_bright_ratio >= PDF_OCR_WORKAROUND_MIN_BRIGHT_RATIO
        )
    finally:
        document.close()


def _prepare_pdf_for_babeldoc(
    input_path: str,
    prepared_path: Path,
    runtime: RuntimeSettings,
) -> tuple[int, bool]:
    document = fitz.open(input_path)
    try:
        has_text_by_page = [_page_has_extractable_text(page) for page in document]
        page_count = document.page_count
        if all(has_text_by_page):
            return page_count, False

        if not runtime.ocr_enabled:
            raise RuntimeError("PDF contains scanned or image-only pages. Enable OCR to preserve layout during translation.")

        prepared_document = fitz.open()
        try:
            for index, has_text in enumerate(has_text_by_page):
                if has_text:
                    prepared_document.insert_pdf(document, from_page=index, to_page=index)
                    continue

                source_page = document[index]
                target_page = prepared_document.new_page(width=source_page.rect.width, height=source_page.rect.height)
                for rect, text in _ocr_page_lines(source_page, runtime):
                    _insert_background_text_best_fit(target_page, rect, text)
                target_page.show_pdf_page(source_page.rect, document, index)
            prepared_document.save(prepared_path)
        finally:
            prepared_document.close()

        if not _pdf_has_any_extractable_text(prepared_path):
            raise RuntimeError("OCR could not detect usable text in this PDF. Please try a clearer scan or a native-text PDF.")
        return page_count, True
    finally:
        document.close()


def _run_command_with_cancellation(
    command: list[str],
    *,
    session: Session,
    job: TranslationJob,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        while process.poll() is None:
            ensure_not_cancelled(session, job)
            time.sleep(0.5)
        stdout, stderr = process.communicate()
    except JobCancelledError:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        raise

    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "BabelDOC failed").strip()
        raise RuntimeError(f"BabelDOC translation failed: {error_text[-4000:]}")
    return completed


def _find_babeldoc_mono_output(output_dir: Path, input_stem: str) -> Path:
    matches = sorted(output_dir.glob(f"{input_stem}*.mono.pdf"))
    if not matches:
        matches = sorted(output_dir.glob("*.mono.pdf"))
    if not matches:
        raise RuntimeError("BabelDOC finished without producing a monolingual PDF output")
    return max(matches, key=lambda candidate: candidate.stat().st_mtime)


def _optimize_pdf_in_place(path: Path, working_root: Path) -> None:
    optimized_path = working_root / f"{path.stem}.optimized{path.suffix}"
    document = fitz.open(path)
    try:
        try:
            document.subset_fonts()
        except Exception:
            pass
        document.save(optimized_path, garbage=4, deflate=True, clean=True, deflate_fonts=True)
    finally:
        document.close()
    shutil.move(str(optimized_path), path)


def _paragraph_targets(document: Document) -> list:
    targets = [paragraph for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                targets.extend(paragraph for paragraph in cell.paragraphs if paragraph.text.strip())
    return targets


def replace_paragraph_text(paragraph, text: str) -> None:
    element = paragraph._element
    for child in list(element):
        if child.tag.endswith("}r") or child.tag.endswith("}hyperlink"):
            element.remove(child)
    paragraph.add_run(text)


def translate_docx(
    input_path: str,
    output_path: Path,
    translator: OpenAICompatibleTranslator,
    job: TranslationJob,
    session: Session,
) -> int | None:
    document = Document(input_path)
    targets = _paragraph_targets(document)
    texts = [paragraph.text for paragraph in targets]

    def on_progress(index: int, total: int) -> None:
        progress = 20 + int((index / max(total, 1)) * 60)
        update_job_state(session, job, status=JobStatus.TRANSLATING, progress=progress)

    translated = translate_segments(
        translator,
        texts,
        source_language=job.source_language,
        target_language=job.target_language,
        preserve_line_breaks=True,
        on_progress=on_progress,
        cancel_check=lambda: ensure_not_cancelled(session, job),
    )
    for paragraph, translated_text in zip(targets, translated, strict=True):
        replace_paragraph_text(paragraph, translated_text)
    document.save(output_path)
    return None


def translate_pdf(
    input_path: str,
    output_path: Path,
    runtime: RuntimeSettings,
    job: TranslationJob,
    session: Session,
) -> int:
    source_language = _babeldoc_language_code(job.source_language, allow_auto=True)
    target_language = _babeldoc_language_code(job.target_language, allow_auto=False)

    with tempfile.TemporaryDirectory(prefix="babeldoc-") as temp_dir:
        temp_root = Path(temp_dir)
        prepared_input_path = temp_root / Path(input_path).name
        output_dir = temp_root / "output"
        working_dir = temp_root / "working"
        output_dir.mkdir(parents=True, exist_ok=True)
        working_dir.mkdir(parents=True, exist_ok=True)

        page_count, used_ocr = _prepare_pdf_for_babeldoc(input_path, prepared_input_path, runtime)
        babeldoc_input_path = prepared_input_path if used_ocr else Path(input_path)
        use_ocr_workaround = used_ocr or _pdf_prefers_ocr_workaround(babeldoc_input_path)

        if used_ocr:
            update_job_state(session, job, status=JobStatus.OCR_RUNNING, progress=18, message="Prepared searchable PDF for scanned pages")

        update_job_state(
            session,
            job,
            status=JobStatus.TRANSLATING,
            progress=20,
            message="Running layout-preserving PDF translation",
            details={"ocr_workaround": use_ocr_workaround, "ocr_prepared": used_ocr, "pdf_mode": "babeldoc"},
        )

        command = [
            "babeldoc",
            "--files",
            str(babeldoc_input_path),
            "--output",
            str(output_dir),
            "--working-dir",
            str(working_dir),
            "--lang-out",
            target_language,
            "--openai",
            "--openai-model",
            runtime.model_name,
            "--openai-base-url",
            runtime.model_base_url,
            "--openai-api-key",
            runtime.model_api_key,
            "--no-dual",
            "--enhance-compatibility",
            "--split-short-lines",
            "--watermark-output-mode",
            "no_watermark",
        ]
        if source_language:
            command.extend(["--lang-in", source_language])
        if use_ocr_workaround:
            command.extend(["--skip-scanned-detection", "--ocr-workaround"])

        _run_command_with_cancellation(command, session=session, job=job)

        update_job_state(session, job, status=JobStatus.REBUILDING, progress=88, message="Finalizing translated PDF")
        mono_output = _find_babeldoc_mono_output(output_dir, babeldoc_input_path.stem)
        shutil.move(str(mono_output), output_path)
        _optimize_pdf_in_place(output_path, temp_root)

    output_document = fitz.open(output_path)
    try:
        return output_document.page_count
    finally:
        output_document.close()


def test_model_connection(runtime: RuntimeSettings) -> tuple[int, str]:
    translator = OpenAICompatibleTranslator(runtime)
    return translator.test_connection()


def run_translation_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        job = (
            session.query(TranslationJob)
            .options(
                selectinload(TranslationJob.input_file),
                selectinload(TranslationJob.output_file),
                selectinload(TranslationJob.created_by_user),
            )
            .filter(TranslationJob.id == job_id)
            .first()
        )
        if job is None:
            logger.warning("Job not found", extra={"job_id": job_id})
            return
        if job.status == JobStatus.CANCELLED:
            return

        runtime = get_runtime_settings(session)
        update_job_state(session, job, status=JobStatus.PARSING, progress=5, message="Parsing document")
        ensure_not_cancelled(session, job)

        input_file = job.input_file
        input_path = input_file.storage_path
        extension = Path(input_file.original_name).suffix.lower()
        output_path = build_output_target(runtime, input_file.original_name, extension)
        page_count: int | None

        if extension == ".pdf":
            page_count = translate_pdf(input_path, output_path, runtime, job, session)
        elif extension == ".docx":
            translator = OpenAICompatibleTranslator(runtime)
            update_job_state(session, job, status=JobStatus.TRANSLATING, progress=20, message="Translating DOCX content")
            page_count = translate_docx(input_path, output_path, translator, job, session)
            update_job_state(session, job, status=JobStatus.REBUILDING, progress=88, message="Writing translated DOCX")
        else:
            raise RuntimeError("Unsupported file type")

        output_file = JobFile(
            original_name=output_path.name,
            stored_name=output_path.name,
            storage_path=str(output_path),
            content_type=input_file.content_type,
            size_bytes=output_path.stat().st_size,
            checksum=file_checksum(output_path),
            kind=JobFileKind.OUTPUT,
            created_by=job.created_by,
        )
        session.add(output_file)
        session.flush()

        job.output_file_id = output_file.id
        job.page_count = page_count
        update_job_state(session, job, status=JobStatus.COMPLETED, progress=100, message="Translation completed")
        record_audit(
            session,
            action="jobs.completed",
            entity_type="translation_job",
            entity_id=job.id,
            actor_id=job.created_by,
            details={"status": job.status.value, "output_file_id": output_file.id},
        )
        session.commit()
        logger.info("Completed translation job", extra={"job_id": job.id})
    except JobCancelledError:
        if "job" in locals():
            update_job_state(session, job, status=JobStatus.CANCELLED, progress=job.progress, message="Job cancelled")
            record_audit(
                session,
                action="jobs.cancelled",
                entity_type="translation_job",
                entity_id=job.id,
                actor_id=job.created_by,
                details={"status": job.status.value},
            )
            session.commit()
    except Exception as exc:
        if "job" in locals():
            logger.exception("Translation job failed", extra={"job_id": job.id})
            update_job_state(
                session,
                job,
                status=JobStatus.FAILED,
                progress=job.progress,
                error_message=str(exc),
                message="Translation failed",
                details={"error": str(exc)},
            )
            record_audit(
                session,
                action="jobs.failed",
                entity_type="translation_job",
                entity_id=job.id,
                actor_id=job.created_by,
                details={"error": str(exc)},
            )
            session.commit()
        else:
            logger.exception("Translation job failed before loading state", extra={"job_id": job_id})
    finally:
        session.close()
