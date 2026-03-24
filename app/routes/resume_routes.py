from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging
import json
import os
from app.resume_analyzer import analyze_resume_bytes, SUPPORTED_EXTENSIONS
from app.file_storage import save_uploaded_file
from app.database import get_db
from app.profile_store import get_profile, set_default_resume
from app.rate_limiter import rate_limiter
from app.settings import get_settings
from app.validators import validate_upload

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
settings = get_settings()

ROLE_TO_TITLE_KEYWORDS = {
    "Software Developer": ["software", "developer", "engineer", "python", "java"],
    "Web Developer": ["web", "frontend", "front end", "react", "javascript"],
    "Backend Developer": ["backend", "back end", "api", "python", "java", "node"],
    "Data Analyst": ["data analyst", "analyst", "bi", "sql"],
    "ML Engineer": ["machine learning", "ml", "ai", "data science"],
}


def _load_jobs():
    jobs_path = os.path.join(os.getcwd(), "jobs.json")
    try:
        with open(jobs_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return data["jobs"]
    return []


def _match_jobs_by_roles(jobs, roles):
    if not roles:
        return []

    matched = []
    seen = set()
    for role in roles:
        keywords = ROLE_TO_TITLE_KEYWORDS.get(role, [str(role).lower()])
        for job in jobs:
            title = str(job.get("title", "")).lower()
            if any(keyword in title for keyword in keywords):
                key = (str(job.get("title", "")), str(job.get("company", "")), str(job.get("location", "")))
                if key not in seen:
                    seen.add(key)
                    matched.append(job)
    return matched


def _make_job_key(title: str, company: str, location: str) -> str:
    return f"{(title or '').strip().lower()}||{(company or '').strip().lower()}||{(location or '').strip().lower()}"


def _fetch_applied_job_keys(user_email: str) -> set[str]:
    if not user_email:
        return set()

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        try:
            cursor.execute(
                """
                SELECT job_title, company, location
                FROM job_applications
                WHERE email=%s
                """,
                (user_email,),
            )
        except Exception:
            return set()
        rows = cursor.fetchall() or []
        return {
            _make_job_key(row.get("job_title", ""), row.get("company", ""), row.get("location", ""))
            for row in rows
        }
    finally:
        cursor.close()
        db.close()


def _annotate_jobs_with_applied(jobs, applied_keys: set[str]):
    output = []
    for job in jobs:
        item = dict(job)
        item["already_applied"] = _make_job_key(item.get("title", ""), item.get("company", ""), item.get("location", "")) in applied_keys
        output.append(item)
    return output


# ---------- RESUME PAGE ----------
@router.get("/resume", response_class=HTMLResponse)
def resume_page(request: Request):
    return templates.TemplateResponse("resume.html", {"request": request})


# ---------- UPLOAD & ANALYZE ----------
@router.post("/resume/upload", response_class=HTMLResponse)
async def upload_resume(request: Request, file: UploadFile = File(...), set_default: str = Form("0")):
    allowed, retry_after = rate_limiter.allow(
        key=f"upload:resume:{request.client.host if request.client else 'unknown'}",
        limit=settings.upload_rate_limit_count,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    safe_name = os.path.basename(file.filename or "")
    _, extension = os.path.splitext(safe_name.lower())

    if not allowed:
        return templates.TemplateResponse("resume_result.html", {
            "request": request,
            "result": {
                "score": 0,
                "skills": [],
                "tips": [f"Too many uploads. Please wait {retry_after}s and try again."],
                "jobs": [],
                "contact": {},
                "sections": {},
                "word_count": 0,
                "file_type": extension or "unknown",
            }
        })

    is_valid, validation_error = validate_upload(
        file,
        allowed_extensions=SUPPORTED_EXTENSIONS,
        max_bytes=settings.max_upload_bytes,
        allowed_content_types={
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        },
    )
    if not is_valid:
        return templates.TemplateResponse("resume_result.html", {
            "request": request,
            "result": {
                "score": 0,
                "skills": [],
                "tips": [
                    validation_error or "Unsupported file type. Please upload PDF, DOCX, or TXT resume."
                ],
                "jobs": [],
                "contact": {},
                "sections": {},
                "word_count": 0,
                "file_type": extension or "unknown",
            }
        })

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_bytes:
        return templates.TemplateResponse("resume_result.html", {
            "request": request,
            "result": {
                "score": 0,
                "skills": [],
                "tips": [f"File is too large. Max size is {settings.max_upload_bytes // (1024 * 1024)} MB."],
                "jobs": [],
                "contact": {},
                "sections": {},
                "word_count": 0,
                "file_type": extension,
            }
        })

    if not file_bytes:
        return templates.TemplateResponse("resume_result.html", {
            "request": request,
            "result": {
                "score": 0,
                "skills": [],
                "tips": ["Uploaded file is empty. Please upload a valid resume file."],
                "jobs": [],
                "contact": {},
                "sections": {},
                "word_count": 0,
                "file_type": extension,
            }
        })

    user_email = (request.session.get("user_email") or "").strip().lower()
    set_as_default = str(set_default).strip() in {"1", "true", "on", "yes"}
    resume_file_id = save_uploaded_file(
        owner_email=user_email,
        original_filename=safe_name,
        content_type=(file.content_type or "").strip(),
        extension=extension,
        purpose="resume_analysis",
        file_bytes=file_bytes,
    )
    if user_email and set_as_default:
        set_default_resume(user_email, resume_file_id)
    logger.info("Resume uploaded email=%s file=%s size=%s", user_email, safe_name, len(file_bytes))

    result = analyze_resume_bytes(file_bytes, extension)
    profile = get_profile(user_email) if user_email else {}
    candidate = {
        "full_name": (request.session.get("user", "") if "@" not in str(request.session.get("user", "")) else "") or result.get("contact", {}).get("name") or "",
        "email": user_email or result.get("contact", {}).get("email") or "",
        "phone": profile.get("phone") or result.get("contact", {}).get("phone") or "",
        "linkedin_url": profile.get("linkedin_url") or result.get("contact", {}).get("linkedin") or "",
        "github_url": profile.get("github_url") or result.get("contact", {}).get("github") or "",
    }
    recommended_jobs = _match_jobs_by_roles(_load_jobs(), result.get("jobs", []))
    applied_keys = _fetch_applied_job_keys(user_email)
    recommended_jobs = _annotate_jobs_with_applied(recommended_jobs, applied_keys)

    return templates.TemplateResponse("resume_result.html", {
        "request": request,
        "result": result,
        "recommended_jobs": recommended_jobs,
        "resume_filename": safe_name,
        "resume_file_id": resume_file_id,
        "user_name": request.session.get("user", ""),
        "user_email": request.session.get("user_email", ""),
        "candidate": candidate,
        "set_as_default": set_as_default,
    })
