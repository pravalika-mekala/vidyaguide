import logging
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt

from app.auth import create_user_with_hash, verify_user, reset_user_password, user_exists
from app.database import get_db
from app.otp_service import create_otp_request, verify_otp, clear_otp
from app.rate_limiter import rate_limiter
from app.settings import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
settings = get_settings()

OTP_EXPIRY_SECONDS = settings.otp_ttl_seconds

PROFILE_FIELD_KEYS = (
    "phone",
    "current_location",
    "education_level",
    "course_name",
    "graduation_year",
    "college",
    "experience_years",
    "preferred_roles",
    "preferred_locations",
    "professional_title",
    "professional_titles",
    "linkedin_url",
    "github_url",
    "skills_summary",
    "bio",
)

EDUCATION_LEVEL_VALUES = {"", "UG", "PG", "Diploma", "PhD", "Other"}


def _is_admin_email(email: str) -> bool:
    normalized = (email or "").strip().lower()
    return normalized in settings.admin_emails


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limit_auth_action(request: Request, action: str) -> str:
    allowed, retry_after = rate_limiter.allow(
        key=f"auth:{action}:{_client_ip(request)}",
        limit=settings.auth_rate_limit_count,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    if allowed:
        return ""
    return f"Too many attempts. Please wait {retry_after}s and try again."


def _normalize_education_level(value: str) -> str:
    normalized = (value or "").strip()
    return normalized if normalized in EDUCATION_LEVEL_VALUES else ""


def _normalize_profile_form_data(
    phone: str,
    current_location: str,
    education_level: str,
    course_name: str,
    graduation_year: str,
    college: str,
    experience_years: str,
    preferred_roles: str,
    preferred_locations: str,
    professional_title: str,
    professional_titles: str,
    linkedin_url: str,
    github_url: str,
    skills_summary: str,
    bio: str,
) -> dict:
    try:
        exp = float((experience_years or "0").strip() or 0)
    except ValueError:
        exp = 0.0

    grad_year = (graduation_year or "").strip()
    if grad_year:
        if not grad_year.isdigit():
            grad_year = ""
        else:
            year_int = int(grad_year)
            if year_int < 1990 or year_int > 2100:
                grad_year = ""

    return {
        "phone": (phone or "").strip(),
        "current_location": (current_location or "").strip(),
        "education_level": _normalize_education_level(education_level),
        "course_name": (course_name or "").strip(),
        "graduation_year": grad_year,
        "college": (college or "").strip(),
        "experience_years": max(0.0, exp),
        "preferred_roles": (preferred_roles or "").strip(),
        "preferred_locations": (preferred_locations or "").strip(),
        "professional_title": (professional_title or "").strip(),
        "professional_titles": (professional_titles or "").strip(),
        "linkedin_url": (linkedin_url or "").strip(),
        "github_url": (github_url or "").strip(),
        "skills_summary": (skills_summary or "").strip(),
        "bio": (bio or "").strip(),
    }


def _signup_template_context(request: Request, name: str, email: str, profile_data: dict, error: str):
    context = {
        "request": request,
        "error": error,
        "name": name,
        "email": email,
    }
    for key in PROFILE_FIELD_KEYS:
        context[key] = profile_data.get(key, "")
    return context

def _save_signup_pending(name: str, email: str, password_hash: str, profile_data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO signup_pending (
                email, name, password_hash, phone, current_location, education_level,
                course_name, graduation_year, college, experience_years,
                preferred_roles, preferred_locations, professional_title, professional_titles,
                linkedin_url, github_url, skills_summary, bio
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name=VALUES(name),
                password_hash=VALUES(password_hash),
                phone=VALUES(phone),
                current_location=VALUES(current_location),
                education_level=VALUES(education_level),
                course_name=VALUES(course_name),
                graduation_year=VALUES(graduation_year),
                college=VALUES(college),
                experience_years=VALUES(experience_years),
                preferred_roles=VALUES(preferred_roles),
                preferred_locations=VALUES(preferred_locations),
                professional_title=VALUES(professional_title),
                professional_titles=VALUES(professional_titles),
                linkedin_url=VALUES(linkedin_url),
                github_url=VALUES(github_url),
                skills_summary=VALUES(skills_summary),
                bio=VALUES(bio),
                created_at=CURRENT_TIMESTAMP
            """,
            (
                email,
                name,
                password_hash,
                profile_data["phone"],
                profile_data["current_location"],
                profile_data["education_level"],
                profile_data["course_name"],
                profile_data["graduation_year"],
                profile_data["college"],
                profile_data["experience_years"],
                profile_data["preferred_roles"],
                profile_data["preferred_locations"],
                profile_data["professional_title"],
                profile_data["professional_titles"],
                profile_data["linkedin_url"],
                profile_data["github_url"],
                profile_data["skills_summary"],
                profile_data["bio"],
            ),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def _get_signup_pending(email: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT email, name, password_hash, phone, current_location, education_level,
                   course_name, graduation_year, college, experience_years,
                   preferred_roles, preferred_locations, professional_title, professional_titles,
                   linkedin_url, github_url, skills_summary, bio
            FROM signup_pending
            WHERE email=%s
            """,
            (email,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def _clear_signup_pending(email: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM signup_pending WHERE email=%s", (email,))
        db.commit()
    finally:
        cursor.close()
        db.close()


def _save_signup_profile(email: str, profile_data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO user_profiles (
                email, phone, college, experience_years, current_location, preferred_locations,
                preferred_roles, professional_title, professional_titles, linkedin_url, github_url,
                skills_summary, bio, education_level, course_name, graduation_year
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                phone=VALUES(phone),
                college=VALUES(college),
                experience_years=VALUES(experience_years),
                current_location=VALUES(current_location),
                preferred_locations=VALUES(preferred_locations),
                preferred_roles=VALUES(preferred_roles),
                professional_title=VALUES(professional_title),
                professional_titles=VALUES(professional_titles),
                linkedin_url=VALUES(linkedin_url),
                github_url=VALUES(github_url),
                skills_summary=VALUES(skills_summary),
                bio=VALUES(bio),
                education_level=VALUES(education_level),
                course_name=VALUES(course_name),
                graduation_year=VALUES(graduation_year)
            """,
            (
                email,
                profile_data["phone"],
                profile_data["college"],
                profile_data["experience_years"],
                profile_data["current_location"],
                profile_data["preferred_locations"],
                profile_data["preferred_roles"],
                profile_data["professional_title"],
                profile_data["professional_titles"],
                profile_data["linkedin_url"],
                profile_data["github_url"],
                profile_data["skills_summary"],
                profile_data["bio"],
                profile_data["education_level"],
                profile_data["course_name"],
                profile_data["graduation_year"],
            ),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def _send_otp_email(email: str, otp: str, purpose: str = "reset"):
    smtp_host = settings.smtp_host
    smtp_port = settings.smtp_port
    smtp_user = settings.smtp_user
    smtp_pass = settings.smtp_password
    smtp_sender = settings.smtp_sender or smtp_user
    allow_console_fallback = settings.otp_console_fallback

    if not (smtp_host and smtp_user and smtp_pass and smtp_sender):
        if allow_console_fallback:
            logger.warning("OTP console fallback used for email=%s", email)
            return True, None
        return False, "SMTP is not configured. Add SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_SENDER in .env."

    msg = EmailMessage()
    if purpose == "signup":
        msg["Subject"] = "VidyaGuide Signup OTP Verification"
        intro = "Use this OTP to complete your VidyaGuide account signup."
    else:
        msg["Subject"] = "VidyaGuide Password Reset OTP"
        intro = "Your VidyaGuide OTP is for password reset."
    msg["From"] = smtp_sender
    msg["To"] = email
    msg.set_content(
        f"{intro}\n"
        f"OTP: {otp}\n"
        f"This OTP is valid for {OTP_EXPIRY_SECONDS // 60} minutes.\n"
        "If you did not request this, ignore this message."
    )

    context = ssl.create_default_context()
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15, context=context) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, None
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Use a Gmail App Password, not your normal Gmail password."
    except Exception as exc:
        logger.exception("OTP email delivery failed for email=%s: %s", email, repr(exc))
        return False, "Unable to send OTP email right now. Check SMTP settings and try again."


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    limit_error = _limit_auth_action(request, "login")
    if limit_error:
        return templates.TemplateResponse("login.html", {"request": request, "error": limit_error})

    email = email.strip().lower()
    user = verify_user(email, password)

    if not user:
        logger.info("Login failed for email=%s ip=%s", email, _client_ip(request))
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid Email or Password"
        })

    request.session["user"] = user.get("name") or user["email"]
    request.session["user_email"] = user["email"]
    is_admin = _is_admin_email(user["email"])
    request.session["is_admin"] = is_admin
    logger.info("Login succeeded for email=%s ip=%s", email, _client_ip(request))
    return RedirectResponse("/admin" if is_admin else "/dashboard", status_code=302)


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    context = {"request": request}
    for key in PROFILE_FIELD_KEYS:
        context[key] = ""
    return templates.TemplateResponse("signup.html", context)


@router.post("/signup")
def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    current_location: str = Form(""),
    education_level: str = Form(""),
    course_name: str = Form(""),
    graduation_year: str = Form(""),
    college: str = Form(""),
    experience_years: str = Form("0"),
    preferred_roles: str = Form(""),
    preferred_locations: str = Form(""),
    professional_title: str = Form(""),
    professional_titles: str = Form(""),
    linkedin_url: str = Form(""),
    github_url: str = Form(""),
    skills_summary: str = Form(""),
    bio: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    limit_error = _limit_auth_action(request, "signup")
    name = name.strip()
    email = email.strip().lower()
    profile_data = _normalize_profile_form_data(
        phone=phone,
        current_location=current_location,
        education_level=education_level,
        course_name=course_name,
        graduation_year=graduation_year,
        college=college,
        experience_years=experience_years,
        preferred_roles=preferred_roles,
        preferred_locations=preferred_locations,
        professional_title=professional_title,
        professional_titles=professional_titles,
        linkedin_url=linkedin_url,
        github_url=github_url,
        skills_summary=skills_summary,
        bio=bio,
    )

    if limit_error:
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error=limit_error,
            ),
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error="Password must be at least 8 characters.",
            ),
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error="Password and Confirm Password must match.",
            ),
        )

    if user_exists(email):
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error="An account with this email already exists.",
            ),
        )

    client_ip = _client_ip(request)
    ok, otp, issue_error = create_otp_request(email, client_ip)
    if not ok:
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error=issue_error or "Could not generate OTP right now.",
            ),
        )

    sent, send_error = _send_otp_email(email, otp, purpose="signup")
    if not sent:
        return templates.TemplateResponse(
            "signup.html",
            _signup_template_context(
                request=request,
                name=name,
                email=email,
                profile_data=profile_data,
                error=send_error or "Could not send OTP right now. Please try again.",
            ),
        )

    _save_signup_pending(
        name=name,
        email=email,
        password_hash=bcrypt.hash(password),
        profile_data=profile_data,
    )
    request.session["signup_email"] = email
    logger.info("Signup OTP issued for email=%s ip=%s", email, client_ip)

    return templates.TemplateResponse("signup_verify_otp.html", {
        "request": request,
        "email": email,
        "name": name,
        "success": "OTP sent successfully. Verify to complete account creation.",
    })


@router.get("/signup/verify", response_class=HTMLResponse)
def signup_verify_page(request: Request):
    email = request.session.get("signup_email")
    if not email:
        return RedirectResponse("/signup", status_code=302)

    pending = _get_signup_pending(email)
    if not pending:
        return RedirectResponse("/signup", status_code=302)

    return templates.TemplateResponse("signup_verify_otp.html", {
        "request": request,
        "email": pending["email"],
        "name": pending["name"],
    })


@router.post("/signup/verify", response_class=HTMLResponse)
def signup_verify_otp(request: Request, otp: str = Form(...)):
    email = request.session.get("signup_email")
    if not email:
        return RedirectResponse("/signup", status_code=302)

    pending = _get_signup_pending(email)
    if not pending:
        return RedirectResponse("/signup", status_code=302)

    is_valid, otp_error = verify_otp(email, otp)
    if not is_valid:
        return templates.TemplateResponse("signup_verify_otp.html", {
            "request": request,
            "email": pending["email"],
            "name": pending["name"],
            "error": otp_error or "Invalid OTP. Please try again.",
        })

    ok, error = create_user_with_hash(pending["name"], pending["email"], pending["password_hash"])
    if not ok:
        return templates.TemplateResponse("signup_verify_otp.html", {
            "request": request,
            "email": pending["email"],
            "name": pending["name"],
            "error": error,
        })

    _save_signup_profile(
        email=pending["email"],
        profile_data=_normalize_profile_form_data(
            phone=pending.get("phone") or "",
            current_location=pending.get("current_location") or "",
            education_level=pending.get("education_level") or "",
            course_name=pending.get("course_name") or "",
            graduation_year=pending.get("graduation_year") or "",
            college=pending.get("college") or "",
            experience_years=str(pending.get("experience_years") or "0"),
            preferred_roles=pending.get("preferred_roles") or "",
            preferred_locations=pending.get("preferred_locations") or "",
            professional_title=pending.get("professional_title") or "",
            professional_titles=pending.get("professional_titles") or "",
            linkedin_url=pending.get("linkedin_url") or "",
            github_url=pending.get("github_url") or "",
            skills_summary=pending.get("skills_summary") or "",
            bio=pending.get("bio") or "",
        ),
    )

    clear_otp(email)
    _clear_signup_pending(email)
    request.session.pop("signup_email", None)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "success": "Account created successfully. Please login.",
    })


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@router.post("/forgot-password/send-otp", response_class=HTMLResponse)
def send_otp(request: Request, email: str = Form(...)):
    limit_error = _limit_auth_action(request, "forgot_password")
    email = email.strip().lower()
    client_ip = _client_ip(request)

    if limit_error:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": limit_error,
            "email": email,
        })

    account_exists = user_exists(email)
    if not account_exists:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": "This email is not registered. Please sign up first.",
            "email": email,
        })

    ok, otp, issue_error = create_otp_request(email, client_ip)
    if not ok:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": issue_error or "Could not generate OTP right now.",
            "email": email,
        })

    sent, send_error = _send_otp_email(email, otp, purpose="reset")
    if not sent:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": send_error or "Could not send OTP right now. Please try again.",
            "email": email,
        })

    request.session["reset_email"] = email
    logger.info("Password reset OTP issued for email=%s ip=%s", email, client_ip)

    return templates.TemplateResponse("verify_otp.html", {
        "request": request,
        "email": email,
        "success": "OTP sent successfully. Check your email.",
    })


@router.get("/forgot-password/verify", response_class=HTMLResponse)
def verify_otp_page(request: Request):
    email = request.session.get("reset_email")
    if not email:
        return RedirectResponse("/forgot-password", status_code=302)
    return templates.TemplateResponse("verify_otp.html", {
        "request": request,
        "email": email,
    })


@router.post("/forgot-password/verify", response_class=HTMLResponse)
def verify_otp_and_reset(
    request: Request,
    otp: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    email = request.session.get("reset_email")

    if not email:
        return RedirectResponse("/forgot-password", status_code=302)

    is_valid, otp_error = verify_otp(email, otp)
    if not is_valid:
        return templates.TemplateResponse("verify_otp.html", {
            "request": request,
            "email": email,
            "error": otp_error or "Invalid OTP. Please try again.",
        })

    if len(password) < 8:
        return templates.TemplateResponse("verify_otp.html", {
            "request": request,
            "email": email,
            "error": "Password must be at least 8 characters.",
        })

    if password != confirm_password:
        return templates.TemplateResponse("verify_otp.html", {
            "request": request,
            "email": email,
            "error": "Password and Confirm Password must match.",
        })

    ok, error = reset_user_password(email, password)
    if not ok:
        return templates.TemplateResponse("verify_otp.html", {
            "request": request,
            "email": email,
            "error": error,
        })

    clear_otp(email)
    request.session.pop("reset_email", None)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "success": "Password reset successful. Please login with your new password.",
    })
