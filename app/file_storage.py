import os
import tempfile
from typing import Optional

from app.database import get_db


def save_uploaded_file(
    owner_email: str,
    original_filename: str,
    content_type: str,
    extension: str,
    purpose: str,
    file_bytes: bytes,
    category: str = "general",
) -> int:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO uploaded_files
            (owner_email, original_filename, content_type, extension, purpose, category, file_size, file_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                (owner_email or "").strip().lower() or None,
                original_filename,
                content_type,
                extension,
                purpose,
                (category or "general").strip().lower(),
                len(file_bytes),
                file_bytes,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)
    finally:
        cursor.close()
        db.close()


def get_uploaded_file(file_id: int) -> Optional[dict]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, owner_email, original_filename, content_type, extension, purpose, category, file_size, file_data, created_at
            FROM uploaded_files
            WHERE id=%s
            """,
            (file_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def list_uploaded_files_by_purpose(purpose: str, limit: int = 200) -> list[dict]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, owner_email, original_filename, content_type, extension, purpose, category, file_size, created_at
            FROM uploaded_files
            WHERE purpose=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (purpose, limit),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def list_uploaded_files_for_owner(owner_email: str, purposes: list[str] | None = None, limit: int = 200) -> list[dict]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        normalized_email = (owner_email or "").strip().lower()
        if not normalized_email:
            return []

        if purposes:
            placeholders = ", ".join(["%s"] * len(purposes))
            cursor.execute(
                f"""
                SELECT id, owner_email, original_filename, content_type, extension, purpose, category, file_size, created_at
                FROM uploaded_files
                WHERE owner_email=%s AND purpose IN ({placeholders})
                ORDER BY id DESC
                LIMIT %s
                """,
                (normalized_email, *purposes, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, owner_email, original_filename, content_type, extension, purpose, category, file_size, created_at
                FROM uploaded_files
                WHERE owner_email=%s
                ORDER BY id DESC
                LIMIT %s
                """,
                (normalized_email, limit),
            )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def write_temp_file(file_bytes: bytes, extension: str) -> str:
    suffix = extension if extension.startswith(".") else f".{extension}"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file_bytes)
        tmp.flush()
        return tmp.name
    finally:
        tmp.close()


def remove_temp_file(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
