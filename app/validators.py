import os

from fastapi import UploadFile


def validate_upload(
    file: UploadFile,
    *,
    allowed_extensions: set[str],
    max_bytes: int,
    allowed_content_types: set[str] | None = None,
) -> tuple[bool, str]:
    safe_name = os.path.basename(file.filename or "").strip()
    if not safe_name:
        return False, "Missing filename."

    _, extension = os.path.splitext(safe_name.lower())
    if extension not in allowed_extensions:
        return False, "Unsupported file type."

    if allowed_content_types:
        content_type = (file.content_type or "").strip().lower()
        if content_type and content_type not in allowed_content_types:
            return False, "Unexpected content type."

    return True, ""
