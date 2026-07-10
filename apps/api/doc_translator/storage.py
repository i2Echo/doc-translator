import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from doc_translator.settings_service import RuntimeSettings


SUPPORTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_TRANSLATED_FILENAME_LANGUAGE_ALIASES = {
    "auto": "auto",
    "auto detect": "auto",
    "zh": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
    "ja": "ja",
    "japanese": "ja",
    "ko": "ko",
    "korean": "ko",
    "ms": "ms",
    "malay": "ms",
    "th": "th",
    "thai": "th",
    "vi": "vi",
    "vietnamese": "vi",
    "es": "es",
    "spanish": "es",
    "fr": "fr",
    "french": "fr",
    "de": "de",
    "german": "de",
}


def ensure_storage_directories(root_path: str) -> dict[str, Path]:
    root = Path(root_path)
    uploads = root / "uploads"
    results = root / "results"
    temp = root / "tmp"
    for path in (root, uploads, results, temp):
        path.mkdir(parents=True, exist_ok=True)
    return {"root": root, "uploads": uploads, "results": results, "tmp": temp}


def validate_upload_name(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name")
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF and DOCX files are supported")
    return extension


def persist_upload(file: UploadFile, runtime: RuntimeSettings) -> dict:
    extension = validate_upload_name(file.filename)
    directories = ensure_storage_directories(runtime.local_storage_path)
    stored_name = f"{uuid4()}{extension}"
    target_path = directories["uploads"] / stored_name
    temp_path = target_path.with_name(f".{stored_name}.tmp")

    digest = hashlib.sha256()
    max_bytes = runtime.max_upload_mb * 1024 * 1024
    size_bytes = 0

    try:
        with temp_path.open("wb") as output_stream:
            while chunk := file.file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds size limit")
                output_stream.write(chunk)
                digest.update(chunk)

        if size_bytes == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

        temp_path.replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise

    return {
        "original_name": file.filename or stored_name,
        "stored_name": stored_name,
        "storage_path": str(target_path),
        "content_type": SUPPORTED_EXTENSIONS[extension],
        "size_bytes": size_bytes,
        "checksum": digest.hexdigest(),
    }


def translated_output_name(input_name: str, target_language: str, extension: str) -> str:
    stem = Path(input_name).stem
    normalized_language = target_language.strip().casefold()
    language_suffix = _TRANSLATED_FILENAME_LANGUAGE_ALIASES.get(normalized_language, normalized_language or "translated")
    return f"{stem}-{language_suffix}{extension}"


def build_output_target(runtime: RuntimeSettings, input_name: str, extension: str, target_language: str) -> Path:
    directories = ensure_storage_directories(runtime.local_storage_path)
    stem = Path(input_name).stem
    normalized_language = target_language.strip().casefold()
    language_suffix = _TRANSLATED_FILENAME_LANGUAGE_ALIASES.get(normalized_language, normalized_language or "translated")
    return directories["results"] / f"{stem}-{language_suffix}-{uuid4().hex[:8]}{extension}"


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
