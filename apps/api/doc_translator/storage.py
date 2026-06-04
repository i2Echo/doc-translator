import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from doc_translator.settings_service import RuntimeSettings


SUPPORTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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

    digest = hashlib.sha256()
    max_bytes = runtime.max_upload_mb * 1024 * 1024
    size_bytes = 0

    with target_path.open("wb") as output_stream:
        while chunk := file.file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds size limit")
            output_stream.write(chunk)
            digest.update(chunk)

    return {
        "original_name": file.filename or stored_name,
        "stored_name": stored_name,
        "storage_path": str(target_path),
        "content_type": file.content_type or SUPPORTED_EXTENSIONS[extension],
        "size_bytes": size_bytes,
        "checksum": digest.hexdigest(),
    }


def build_output_target(runtime: RuntimeSettings, input_name: str, extension: str) -> Path:
    directories = ensure_storage_directories(runtime.local_storage_path)
    stem = Path(input_name).stem
    return directories["results"] / f"{stem}-translated-{uuid4().hex[:8]}{extension}"


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

