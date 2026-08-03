from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from xml.etree import ElementTree

if TYPE_CHECKING:
    from doc_translator.translation import ModelTranslator

logger = logging.getLogger(__name__)

_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_TEXT_TAG = f"{{{_DRAWING_NS}}}t"
_PARAGRAPH_TAG = f"{{{_DRAWING_NS}}}p"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_PPTX_TEXT_PART_PATTERN = re.compile(r"^ppt/(slides/slide|notesSlides/notesSlide)(\d+)\.xml$")
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
@dataclass(frozen=True)
class PptxTextSection:
    part_name: str
    label: str
    paragraphs: list[str]


@dataclass(frozen=True)
class _PptxTextTarget:
    part_name: str
    paragraph_index: int
    text: str


def _text_part_sort_key(name: str) -> tuple[int, int, str]:
    match = _PPTX_TEXT_PART_PATTERN.match(name)
    if match is None:
        return (2, 0, name)
    part_prefix, raw_index = match.groups()
    return (0 if part_prefix == "slides/slide" else 1, int(raw_index), name)


def _text_part_label(name: str) -> str:
    match = _PPTX_TEXT_PART_PATTERN.match(name)
    if match is None:
        return name
    part_prefix, raw_index = match.groups()
    return f"Slide {int(raw_index)}" if part_prefix == "slides/slide" else f"Notes {int(raw_index)}"


def _iter_text_part_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted((name for name in archive.namelist() if _PPTX_TEXT_PART_PATTERN.match(name)), key=_text_part_sort_key)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(text_element.text or "" for text_element in paragraph.iter(_TEXT_TAG))


def _set_text(element: ElementTree.Element, text: str) -> None:
    element.text = text
    if text[:1].isspace() or text[-1:].isspace():
        element.set(_XML_SPACE, "preserve")
    else:
        element.attrib.pop(_XML_SPACE, None)


def _replace_paragraph_text(paragraph: ElementTree.Element, text: str) -> None:
    text_elements = list(paragraph.iter(_TEXT_TAG))
    if not text_elements:
        raise ValueError("PPTX paragraph has no editable text")
    first, *rest = text_elements
    _set_text(first, text)
    for element in rest:
        _set_text(element, "")


def _parse_xml(data: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise RuntimeError("PPTX contains invalid slide XML") from exc


def read_pptx_text_sections(path: str | Path) -> list[PptxTextSection]:
    sections: list[PptxTextSection] = []
    with zipfile.ZipFile(path) as archive:
        for part_name in _iter_text_part_names(archive):
            root = _parse_xml(archive.read(part_name))
            paragraphs = [_paragraph_text(paragraph).strip() for paragraph in root.iter(_PARAGRAPH_TAG)]
            sections.append(
                PptxTextSection(
                    part_name=part_name,
                    label=_text_part_label(part_name),
                    paragraphs=[text for text in paragraphs if text],
                )
            )
    return sections


def _collect_targets(path: str | Path) -> list[_PptxTextTarget]:
    targets: list[_PptxTextTarget] = []
    with zipfile.ZipFile(path) as archive:
        for part_name in _iter_text_part_names(archive):
            root = _parse_xml(archive.read(part_name))
            for paragraph_index, paragraph in enumerate(root.iter(_PARAGRAPH_TAG)):
                text = _paragraph_text(paragraph).strip()
                if text:
                    targets.append(_PptxTextTarget(part_name, paragraph_index, text))
    return targets


def _write_pptx_with_replacements(
    input_path: str | Path,
    output_path: Path,
    replacements: dict[tuple[str, int], str],
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        with zipfile.ZipFile(input_path) as source_archive:
            text_parts = set(_iter_text_part_names(source_archive))
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as target_archive:
                for item in source_archive.infolist():
                    data = source_archive.read(item.filename)
                    if item.filename in text_parts:
                        root = _parse_xml(data)
                        for paragraph_index, paragraph in enumerate(root.iter(_PARAGRAPH_TAG)):
                            replacement = replacements.get((item.filename, paragraph_index))
                            if replacement is not None:
                                _replace_paragraph_text(paragraph, replacement)
                        data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
                    target_archive.writestr(item, data)

        with zipfile.ZipFile(temp_path) as validation_archive:
            if "[Content_Types].xml" not in validation_archive.namelist():
                raise RuntimeError("Translated PPTX package is invalid")
        temp_path.replace(output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def replace_pptx_paragraphs(
    output_path: Path,
    replacements: dict[tuple[str, int], str],
) -> None:
    _write_pptx_with_replacements(output_path, output_path, replacements)


def convert_ppt_to_pptx(input_path: str | Path, output_dir: Path) -> Path:
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if converter is None:
        raise RuntimeError("Legacy PPT translation requires LibreOffice in the worker container")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(input_path)
    completed = subprocess.run(
        [
            converter,
            "--headless",
            "--convert-to",
            "pptx",
            "--outdir",
            str(output_dir),
            str(source_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    converted_path = output_dir / f"{source_path.stem}.pptx"
    if completed.returncode != 0 or not converted_path.exists():
        details = " ".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        raise RuntimeError(f"Could not convert PPT to PPTX: {details or 'LibreOffice conversion failed'}")
    return converted_path


def convert_office_to_pdf(input_path: str | Path, output_dir: Path) -> Path:
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if converter is None:
        raise RuntimeError("PPT preview rendering requires LibreOffice in the worker container")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(input_path)
    completed = subprocess.run(
        [
            converter,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    converted_path = output_dir / f"{source_path.stem}.pdf"
    if completed.returncode != 0 or not converted_path.exists():
        details = " ".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        raise RuntimeError(f"Could not convert Office file to PDF: {details or 'LibreOffice conversion failed'}")
    return converted_path


def translate_pptx(
    input_path: str,
    output_path: Path,
    *,
    translator: ModelTranslator,
    translate_segments: Callable[..., list[str]],
    source_language: str,
    target_language: str,
    on_progress: Callable[[int, int], None],
    cancel_check: Callable[[], None],
    on_rebuilding: Callable[[], None],
) -> int | None:
    started_at = time.perf_counter()
    targets = _collect_targets(input_path)

    if targets:
        translated = translate_segments(
            translator,
            [target.text for target in targets],
            source_language=source_language,
            target_language=target_language,
            preserve_line_breaks=True,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )
    else:
        translated = []
        logger.info("PPTX contains no translatable text", extra={"input": input_path})

    if len(translated) != len(targets):
        raise RuntimeError(
            f"PPTX translation returned {len(translated)} results for {len(targets)} text paragraphs"
        )

    cancel_check()
    on_rebuilding()
    replacements = {
        (target.part_name, target.paragraph_index): translated_text
        for target, translated_text in zip(targets, translated, strict=True)
    }
    _write_pptx_with_replacements(input_path, output_path, replacements)
    cancel_check()

    slide_count = sum(1 for section in read_pptx_text_sections(output_path) if section.part_name.startswith("ppt/slides/"))
    logger.info(
        "Saved translated PPTX",
        extra={
            "output": str(output_path),
            "slides": slide_count,
            "paragraphs": len(targets),
            "total_seconds": round(time.perf_counter() - started_at, 3),
        },
    )
    return slide_count or None
