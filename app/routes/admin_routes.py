from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from mysql.connector import Error as MySQLError

from app.database import get_db
from app.settings import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")
settings = get_settings()


def _require_admin(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    if not request.session.get("is_admin"):
        return RedirectResponse("/dashboard", status_code=302)
    return None


def _admin_email_set() -> set[str]:
    return settings.admin_emails


def _fetch_users_with_profiles(limit: int = 500):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT u.id, u.name, u.email, u.is_active,
                   p.phone, p.college, p.experience_years, p.current_location,
                   p.preferred_locations, p.professional_title, p.skills_summary,
                   p.professional_titles, p.linkedin_url, p.github_url,
                   p.education_level, p.course_name, p.graduation_year, p.updated_at
            FROM users u
            LEFT JOIN user_profiles p ON p.email = u.email
            ORDER BY u.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


def _fetch_all_applications(limit: int = 500):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, full_name, email, phone, linkedin_url, github_url, job_title, company, location,
                   detected_skills, resume_filename, resume_file_id, created_at
            FROM job_applications
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        db.close()


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    request.session["admin_mode"] = True

    users = _fetch_users_with_profiles(limit=5)
    applications = _fetch_all_applications(limit=5)
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "users": users,
            "applications": applications,
            "total_users": len(_fetch_users_with_profiles(limit=5000)),
            "total_applications": len(_fetch_all_applications(limit=5000)),
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    users = _fetch_users_with_profiles(limit=1000)
    admin_set = _admin_email_set()
    for row in users:
        email = (row.get("email") or "").strip().lower()
        row["role"] = "Admin" if email in admin_set else "User"

    admin_count = len([u for u in users if u.get("role") == "Admin"])
    user_count = len(users) - admin_count
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "total_users": len(users),
            "admin_count": admin_count,
            "user_count": user_count,
            "deleted": request.query_params.get("deleted") == "1",
            "deactivated": request.query_params.get("deactivated") == "1",
            "reactivated": request.query_params.get("reactivated") == "1",
            "error": request.query_params.get("error", ""),
        },
    )


@router.get("/admin/applications", response_class=HTMLResponse)
def admin_applications(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    applications = _fetch_all_applications(limit=1000)
    return templates.TemplateResponse(
        "admin_applications.html",
        {
            "request": request,
            "applications": applications,
            "total_applications": len(applications),
        },
    )


def _delete_user_and_related(user_id: int, requester_email: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False, "not_found"

        user_email = (row.get("email") or "").strip().lower()
        if not user_email:
            return False, "not_found"
        if user_email == requester_email:
            return False, "self_delete"

        # Best-effort cleanup for optional tables in this project.
        for query, params in [
            ("DELETE FROM job_applications WHERE email=%s", (user_email,)),
            ("DELETE FROM user_profiles WHERE email=%s", (user_email,)),
            ("DELETE FROM learning_profiles WHERE email=%s", (user_email,)),
            ("DELETE FROM daily_task_progress WHERE email=%s", (user_email,)),
            ("DELETE FROM uploaded_files WHERE owner_email=%s", (user_email,)),
            ("DELETE FROM users WHERE id=%s", (user_id,)),
        ]:
            try:
                cursor.execute(query, params)
            except MySQLError as exc:
                # Ignore missing table errors for optional modules.
                if getattr(exc, "errno", None) != 1146:
                    raise

        db.commit()
        return True, ""
    finally:
        cursor.close()
        db.close()


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    requester_email = (request.session.get("user_email") or "").strip().lower()
    ok, code = _delete_user_and_related(user_id=user_id, requester_email=requester_email)
    if ok:
        return RedirectResponse("/admin/users?deleted=1", status_code=302)
    return RedirectResponse(f"/admin/users?error={code}", status_code=302)


def _set_user_active_state(user_id: int, requester_email: str, active: bool):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False, "not_found"

        user_email = (row.get("email") or "").strip().lower()
        if not user_email:
            return False, "not_found"
        if user_email == requester_email:
            return False, "self_deactivate" if not active else "self_action"

        cursor.execute("UPDATE users SET is_active=%s WHERE id=%s", (1 if active else 0, user_id))
        db.commit()
        return True, ""
    finally:
        cursor.close()
        db.close()


@router.post("/admin/users/{user_id}/deactivate")
def admin_deactivate_user(request: Request, user_id: int):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    requester_email = (request.session.get("user_email") or "").strip().lower()
    ok, code = _set_user_active_state(user_id=user_id, requester_email=requester_email, active=False)
    if ok:
        return RedirectResponse("/admin/users?deactivated=1", status_code=302)
    return RedirectResponse(f"/admin/users?error={code}", status_code=302)


@router.post("/admin/users/{user_id}/reactivate")
def admin_reactivate_user(request: Request, user_id: int):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    requester_email = (request.session.get("user_email") or "").strip().lower()
    ok, code = _set_user_active_state(user_id=user_id, requester_email=requester_email, active=True)
    if ok:
        return RedirectResponse("/admin/users?reactivated=1", status_code=302)
    return RedirectResponse(f"/admin/users?error={code}", status_code=302)
