import os
from collections import defaultdict
import logging
import re

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.file_storage import save_uploaded_file, get_uploaded_file, list_uploaded_files_by_purpose
from app.rate_limiter import rate_limiter
from app.settings import get_settings
from app.validators import validate_upload

router = APIRouter()
templates = Jinja2Templates(directory="templates")
DEFAULT_DOMAINS = ["dbms", "os", "dsa", "general"]
logger = logging.getLogger(__name__)
settings = get_settings()


def _is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


@router.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    materials = list_uploaded_files_by_purpose("study_material", limit=300)
    grouped = defaultdict(list)
    for item in materials:
        category = (item.get("category") or "general").strip().lower()
        grouped[category].append(item)

    dynamic_domains = sorted([d for d in grouped.keys() if d and d not in DEFAULT_DOMAINS])
    ordered_domains = DEFAULT_DOMAINS + dynamic_domains
    materials_by_category = {domain: grouped.get(domain, []) for domain in ordered_domains}
    domain_labels = {domain: domain.upper() if domain in {"dbms", "os", "dsa"} else domain.title() for domain in ordered_domains}
    has_materials = any(materials_by_category.values())
    return templates.TemplateResponse(
        "materials.html",
        {
            "request": request,
            "materials_by_category": materials_by_category,
            "material_domains": ordered_domains,
            "domain_labels": domain_labels,
            "has_materials": has_materials,
            "uploaded": request.query_params.get("uploaded") == "1",
            "deleted": request.query_params.get("deleted") == "1",
            "error": request.query_params.get("error", ""),
            "is_admin": _is_admin(request),
            "admin_mode": request.session.get("admin_mode", False),
        },
    )


@router.post("/materials/upload")
async def upload_material(
    request: Request,
    category: str = Form(""),
    file: UploadFile = File(...),
):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    if not _is_admin(request):
        return RedirectResponse("/materials?error=not_allowed", status_code=302)

    allowed, _ = rate_limiter.allow(
        key=f"upload:materials:{request.client.host if request.client else 'unknown'}",
        limit=settings.upload_rate_limit_count,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    if not allowed:
        return RedirectResponse("/materials?error=empty_file", status_code=302)

    safe_name = os.path.basename(file.filename or "").strip()
    is_valid, _ = validate_upload(
        file,
        allowed_extensions={".pdf"},
        max_bytes=settings.max_upload_bytes,
        allowed_content_types={"application/pdf"},
    )
    if not is_valid:
        return RedirectResponse("/materials?error=only_pdf", status_code=302)

    category = (category or "").strip().lower()
    if not category:
        category = "general"
    # Keep domain names clean and predictable for grouping.
    category = re.sub(r"\s+", "_", category)
    category = re.sub(r"[^a-z0-9_+-]", "", category)
    if not category or len(category) > 40:
        return RedirectResponse("/materials?error=invalid_category", status_code=302)

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_bytes:
        return RedirectResponse("/materials?error=empty_file", status_code=302)
    if not file_bytes:
        return RedirectResponse("/materials?error=empty_file", status_code=302)

    user_email = (request.session.get("user_email") or "").strip().lower()
    save_uploaded_file(
        owner_email=user_email,
        original_filename=safe_name or "material.pdf",
        content_type=(file.content_type or "application/pdf").strip(),
        extension=".pdf",
        purpose="study_material",
        category=category,
        file_bytes=file_bytes,
    )
    logger.info("Study material uploaded email=%s file=%s category=%s", user_email, safe_name, category)
    return RedirectResponse("/materials?uploaded=1", status_code=302)


@router.post("/materials/{file_id}/delete")
def delete_material(request: Request, file_id: int):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    if not _is_admin(request):
        return RedirectResponse("/materials?error=not_allowed", status_code=302)

    file_row = get_uploaded_file(file_id)
    if not file_row:
        return RedirectResponse("/materials?error=file_not_found", status_code=302)
    if (file_row.get("purpose") or "") != "study_material":
        return RedirectResponse("/materials?error=not_allowed", status_code=302)

    from app.database import get_db  # local import to avoid unnecessary import at module load
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM uploaded_files WHERE id=%s AND purpose=%s", (file_id, "study_material"))
        db.commit()
    finally:
        cursor.close()
        db.close()

    return RedirectResponse("/materials?deleted=1", status_code=302)


@router.get("/materials/files/{file_id}")
def download_material(request: Request, file_id: int):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    file_row = get_uploaded_file(file_id)
    if not file_row:
        return Response(status_code=404, content="File not found")
    if (file_row.get("purpose") or "") != "study_material":
        return Response(status_code=403, content="Not authorized")

    is_preview = request.query_params.get("preview") == "1"
    filename = file_row.get("original_filename") or f"material_{file_id}.pdf"
    
    disposition = "inline" if is_preview else "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"'}
    
    return Response(
        content=file_row["file_data"],
        media_type=file_row.get("content_type") or "application/pdf",
        headers=headers,
    )
