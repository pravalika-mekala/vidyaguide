import json
import json
import logging
import os
from typing import List, Dict
import re

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.database import get_db
from app.resume_analyzer import analyze_resume_bytes, SUPPORTED_EXTENSIONS
from app.file_storage import save_uploaded_file, get_uploaded_file, list_uploaded_files_for_owner
from app.profile_store import get_profile, set_default_resume
from app.rate_limiter import rate_limiter
from app.settings import get_settings
from app.validators import validate_upload

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
settings = get_settings()


def load_jobs():
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


def _save_application(
    full_name: str,
    email: str,
    phone: str,
    linkedin_url: str,
    github_url: str,
    job_title: str,
    company: str,
    location: str,
    detected_skills: str,
    resume_filename: str,
    resume_file_id: int,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO job_applications
            (full_name, email, phone, linkedin_url, github_url, job_title, company, location, detected_skills, resume_filename, resume_file_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                full_name,
                email,
                phone,
                linkedin_url,
                github_url,
                job_title,
                company,
                location,
                detected_skills,
                resume_filename,
                resume_file_id if resume_file_id > 0 else None,
            ),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def _fetch_applications(user_email: str, limit: int = 300):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, full_name, email, phone, linkedin_url, github_url, job_title, company, location,
                   detected_skills, resume_filename, resume_file_id, created_at
            FROM job_applications
            WHERE email=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (user_email, limit),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def _make_job_key(title: str, company: str, location: str) -> str:
    return f"{(title or '').strip().lower()}||{(company or '').strip().lower()}||{(location or '').strip().lower()}"


def _fetch_applied_job_keys(user_email: str) -> set[str]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT job_title, company, location
            FROM job_applications
            WHERE email=%s
            """,
            (user_email,),
        )
        rows = cursor.fetchall() or []
        return {
            _make_job_key(row.get("job_title", ""), row.get("company", ""), row.get("location", ""))
            for row in rows
        }
    finally:
        cursor.close()
        db.close()


def _annotate_jobs_with_applied(jobs: List[Dict], applied_keys: set[str]) -> List[Dict]:
    annotated = []
    for job in jobs:
        key = _make_job_key(str(job.get("title", "")), str(job.get("company", "")), str(job.get("location", "")))
        item = dict(job)
        item["already_applied"] = key in applied_keys
        annotated.append(item)
    return annotated


ROLE_TO_TITLE_KEYWORDS = {
    "Software Developer": ["software", "developer", "engineer", "python", "java"],
    "Web Developer": ["web", "frontend", "front end", "react", "javascript"],
    "Backend Developer": ["backend", "back end", "api", "python", "java", "node"],
    "Data Analyst": ["data analyst", "analyst", "bi", "sql"],
    "ML Engineer": ["machine learning", "ml", "ai", "data science"],
}


def _match_jobs_by_roles(jobs: List[Dict], roles: List[str]):
    if not roles:
        return []

    matched = []
    seen = set()
    for role in roles:
        keywords = ROLE_TO_TITLE_KEYWORDS.get(role, [role.lower()])
        for job in jobs:
            title = str(job.get("title", "")).lower()
            if any(keyword in title for keyword in keywords):
                key = (
                    str(job.get("title", "")),
                    str(job.get("company", "")),
                    str(job.get("location", "")),
                )
                if key not in seen:
                    seen.add(key)
                    matched.append(job)
    return matched


def _parse_priority_list(value: str) -> list[str]:
    raw_items = re.split(r"[\n,]+", value or "")
    output = []
    seen = set()
    for item in raw_items:
        cleaned = item.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _rank_jobs_by_preferences(jobs: List[Dict], preferred_roles: list[str], preferred_locations: list[str]) -> List[Dict]:
    role_order = {value.lower(): index for index, value in enumerate(preferred_roles)}
    location_order = {value.lower(): index for index, value in enumerate(preferred_locations)}

    def _score(job: Dict) -> tuple[int, int, str]:
        title = str(job.get("title", "")).lower()
        location = str(job.get("location", "")).lower()

        role_score = len(preferred_roles) + 1
        for role, index in role_order.items():
            if role in title:
                role_score = index
                break

        location_score = len(preferred_locations) + 1
        for place, index in location_order.items():
            if place in location:
                location_score = index
                break

        return role_score, location_score, title

    return sorted(jobs, key=_score)


def _resume_file_choices(user_email: str) -> list[dict]:
    files = list_uploaded_files_for_owner(
        user_email,
        purposes=["resume_analysis", "job_recommendation"],
        limit=25,
    )
    deduped: list[dict] = []
    seen_names: set[str] = set()
    for item in files:
        name_key = str(item.get("original_filename") or "").strip().lower()
        if not name_key or name_key in seen_names:
            continue
        seen_names.add(name_key)
        deduped.append(item)
    return deduped


def _candidate_defaults(request: Request, profile: dict, resume_result: dict | None = None) -> dict:
    contact = (resume_result or {}).get("contact", {}) if resume_result else {}
    user_label = request.session.get("user", "") or ""
    default_name = user_label if "@" not in user_label else ""
    profile_titles = _parse_priority_list(profile.get("professional_titles") or "")
    role_priorities = _parse_priority_list(profile.get("preferred_roles") or "")
    location_priorities = _parse_priority_list(profile.get("preferred_locations") or "")

    return {
        "full_name": default_name or contact.get("name") or "",
        "email": (request.session.get("user_email") or "").strip() or contact.get("email") or "",
        "phone": profile.get("phone") or contact.get("phone") or "",
        "linkedin_url": profile.get("linkedin_url") or contact.get("linkedin") or "",
        "github_url": profile.get("github_url") or contact.get("github") or "",
        "role_priorities": role_priorities,
        "location_priorities": location_priorities,
        "profile_titles": profile_titles,
    }


def _default_resume_context(user_email: str, selected_resume_file_id: int = 0, selected_resume_filename: str = "") -> dict:
    profile = get_profile(user_email) if user_email else {}
    resume_files = _resume_file_choices(user_email) if user_email else []
    default_resume_file_id = int(profile.get("default_resume_file_id") or 0) if profile else 0
    default_resume = next((item for item in resume_files if int(item.get("id") or 0) == default_resume_file_id), None)
    active_resume_file_id = selected_resume_file_id or default_resume_file_id
    active_resume_filename = selected_resume_filename or (default_resume.get("original_filename") if default_resume else "")

    return {
        "profile": profile,
        "resume_files": resume_files,
        "default_resume": default_resume,
        "active_resume_file_id": active_resume_file_id,
        "active_resume_filename": active_resume_filename,
    }


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    jobs = load_jobs()
    applied = request.query_params.get("applied") == "1"
    error_code = request.query_params.get("error", "")
    error_map = {
        "missing_fields": "Please fill all required application fields.",
        "missing_resume": "Resume is mandatory. Upload your resume first and then apply.",
        "missing_profile": "Add at least one profile link: LinkedIn or GitHub.",
        "invalid_linkedin": "LinkedIn URL is invalid. Use a valid linkedin.com profile link.",
        "invalid_github": "GitHub URL is invalid. Use a valid github.com profile link.",
        "already_applied": "You have already applied for this job.",
    }
    apply_error = error_map.get(error_code, "")
    user_name = request.session.get("user", "")
    user_email = request.session.get("user_email", "")
    resume_context = _default_resume_context(user_email)
    candidate_defaults = _candidate_defaults(request, resume_context["profile"])
    applied_keys = _fetch_applied_job_keys(user_email) if user_email else set()
    jobs = _annotate_jobs_with_applied(jobs, applied_keys)
    jobs = _rank_jobs_by_preferences(
        jobs,
        candidate_defaults["role_priorities"] or candidate_defaults["profile_titles"],
        candidate_defaults["location_priorities"],
    )

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": jobs,
        "recommended_jobs": [],
        "detected_skills": [],
        "resume_roles": [],
        "resume_filename": resume_context["active_resume_filename"],
        "resume_file_id": resume_context["active_resume_file_id"],
        "applied": applied,
        "user_name": user_name,
        "user_email": user_email,
        "source": "all",
        "apply_error": apply_error,
        "candidate": candidate_defaults,
        "profile": resume_context["profile"],
        "resume_files": resume_context["resume_files"],
        "default_resume": resume_context["default_resume"],
    })


@router.post("/jobs/recommend", response_class=HTMLResponse)
async def recommend_jobs(request: Request, file: UploadFile = File(...), set_default: str = Form("0")):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    allowed, retry_after = rate_limiter.allow(
        key=f"upload:jobs:{request.client.host if request.client else 'unknown'}",
        limit=settings.upload_rate_limit_count,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    safe_name = os.path.basename(file.filename or "")
    _, extension = os.path.splitext(safe_name.lower())
    all_jobs = load_jobs()
    user_name = request.session.get("user", "")
    user_email = request.session.get("user_email", "")
    resume_context = _default_resume_context(user_email)

    if not allowed:
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": all_jobs,
            "recommended_jobs": [],
            "detected_skills": [],
            "resume_roles": [],
            "resume_filename": "",
            "resume_file_id": 0,
            "error": f"Too many uploads. Please wait {retry_after}s and try again.",
            "applied": False,
            "user_name": user_name,
            "user_email": user_email,
            "source": "all",
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
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": all_jobs,
            "recommended_jobs": [],
            "detected_skills": [],
            "resume_roles": [],
            "resume_filename": "",
            "resume_file_id": 0,
            "error": validation_error or "Unsupported resume type. Upload PDF, DOCX, or TXT.",
            "applied": False,
            "user_name": user_name,
            "user_email": user_email,
            "source": "all",
        })

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_bytes:
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": all_jobs,
            "recommended_jobs": [],
            "detected_skills": [],
            "resume_roles": [],
            "resume_filename": "",
            "resume_file_id": 0,
            "error": f"File is too large. Max size is {settings.max_upload_bytes // (1024 * 1024)} MB.",
            "applied": False,
            "user_name": user_name,
            "user_email": user_email,
            "source": "all",
        })

    if not file_bytes:
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": all_jobs,
            "recommended_jobs": [],
            "detected_skills": [],
            "resume_roles": [],
            "resume_filename": "",
            "resume_file_id": 0,
            "error": "Uploaded file is empty. Please upload a valid resume.",
            "applied": False,
            "user_name": user_name,
            "user_email": user_email,
            "source": "all",
        })

    resume_file_id = save_uploaded_file(
        owner_email=user_email,
        original_filename=safe_name,
        content_type=(file.content_type or "").strip(),
        extension=extension,
        purpose="job_recommendation",
        file_bytes=file_bytes,
    )
    if user_email and str(set_default).strip() in {"1", "true", "on", "yes"}:
        set_default_resume(user_email, resume_file_id)
    resume_context = _default_resume_context(user_email, resume_file_id, safe_name)
    logger.info("Job recommendation resume uploaded email=%s file=%s size=%s", user_email, safe_name, len(file_bytes))

    result = analyze_resume_bytes(file_bytes, extension)
    profile = resume_context["profile"]
    role_preferences = _parse_priority_list(profile.get("preferred_roles") or "")
    location_preferences = _parse_priority_list(profile.get("preferred_locations") or "")
    detected_skills = result.get("skills", [])
    resume_roles = result.get("jobs", [])
    role_candidates = role_preferences or resume_roles or _parse_priority_list(profile.get("professional_titles") or "")
    recommended_jobs = _match_jobs_by_roles(all_jobs, role_candidates or resume_roles)
    applied_keys = _fetch_applied_job_keys(user_email) if user_email else set()
    all_jobs = _annotate_jobs_with_applied(all_jobs, applied_keys)
    recommended_jobs = _annotate_jobs_with_applied(recommended_jobs, applied_keys)
    recommended_jobs = _rank_jobs_by_preferences(recommended_jobs, role_candidates, location_preferences)
    candidate_defaults = _candidate_defaults(request, profile, result)

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": all_jobs,
        "recommended_jobs": recommended_jobs,
        "detected_skills": detected_skills,
        "resume_roles": resume_roles,
        "resume_filename": safe_name,
        "resume_file_id": resume_file_id,
        "applied": False,
        "user_name": user_name,
        "user_email": user_email,
        "source": "recommended",
        "apply_error": "",
        "candidate": candidate_defaults,
        "profile": profile,
        "resume_files": resume_context["resume_files"],
        "default_resume": resume_context["default_resume"],
    })


@router.post("/jobs/apply")
def apply_job(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    linkedin_url: str = Form(""),
    github_url: str = Form(""),
    job_title: str = Form(...),
    company: str = Form(""),
    location: str = Form(""),
    detected_skills: str = Form(""),
    resume_filename: str = Form(""),
    resume_file_id: int = Form(0),
):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    allowed, _ = rate_limiter.allow(
        key=f"auth:job_apply:{request.client.host if request.client else 'unknown'}",
        limit=settings.auth_rate_limit_count,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    if not allowed:
        return RedirectResponse("/jobs?applied=0&error=missing_fields", status_code=302)

    session_email = (request.session.get("user_email") or "").strip().lower()
    full_name = full_name.strip()
    email = session_email or email.strip().lower()
    phone = phone.strip()
    linkedin_url = linkedin_url.strip()
    github_url = github_url.strip()

    if not full_name or not email or not phone:
        return RedirectResponse("/jobs?applied=0&error=missing_fields", status_code=302)
    if resume_file_id <= 0:
        return RedirectResponse("/jobs?applied=0&error=missing_resume", status_code=302)

    if not linkedin_url and not github_url:
        return RedirectResponse("/jobs?applied=0&error=missing_profile", status_code=302)

    if linkedin_url and not re.match(r"^(https?://)?(www\.)?linkedin\.com/.*", linkedin_url, flags=re.IGNORECASE):
        return RedirectResponse("/jobs?applied=0&error=invalid_linkedin", status_code=302)

    if github_url and not re.match(r"^(https?://)?(www\.)?github\.com/.*", github_url, flags=re.IGNORECASE):
        return RedirectResponse("/jobs?applied=0&error=invalid_github", status_code=302)

    if _make_job_key(job_title, company, location) in _fetch_applied_job_keys(email):
        return RedirectResponse("/jobs?applied=0&error=already_applied", status_code=302)

    _save_application(
        full_name=full_name,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        github_url=github_url,
        job_title=job_title.strip(),
        company=company.strip(),
        location=location.strip(),
        detected_skills=detected_skills.strip(),
        resume_filename=resume_filename.strip(),
        resume_file_id=resume_file_id,
    )
    logger.info("Job application saved email=%s job_title=%s company=%s", email, job_title.strip(), company.strip())
    return RedirectResponse("/jobs?applied=1", status_code=302)


@router.post("/jobs/default-resume/{file_id}")
def set_default_resume_route(request: Request, file_id: int):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    file_row = get_uploaded_file(file_id)
    if not file_row:
        return RedirectResponse("/jobs", status_code=302)

    owner_email = (file_row.get("owner_email") or "").strip().lower()
    if owner_email != user_email:
        return RedirectResponse("/jobs", status_code=302)

    if (file_row.get("purpose") or "") not in {"resume_analysis", "job_recommendation"}:
        return RedirectResponse("/jobs", status_code=302)

    set_default_resume(user_email, file_id)
    logger.info("Default resume updated email=%s file_id=%s", user_email, file_id)
    return RedirectResponse("/jobs", status_code=302)


@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    applications = _fetch_applications(user_email=user_email)
    return templates.TemplateResponse("applications.html", {
        "request": request,
        "applications": applications,
        "total": len(applications),
    })


@router.get("/files/{file_id}")
def download_stored_file(request: Request, file_id: int):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)
    is_admin = bool(request.session.get("is_admin"))

    file_row = get_uploaded_file(file_id)
    if not file_row:
        return Response(status_code=404, content="File not found")
    owner_email = (file_row.get("owner_email") or "").strip().lower()
    if not is_admin and (not owner_email or owner_email != user_email):
        return Response(status_code=403, content="Not authorized to access this file")

    filename = file_row.get("original_filename") or f"file_{file_id}"
    content_type = file_row.get("content_type") or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=file_row["file_data"], media_type=content_type, headers=headers)
