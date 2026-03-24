from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.profile_store import get_profile, save_profile

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    profile = get_profile(user_email)
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "profile": profile, "saved": request.query_params.get("saved") == "1"},
    )


@router.post("/profile")
def save_profile_route(
    request: Request,
    phone: str = Form(""),
    college: str = Form(""),
    experience_years: float = Form(0),
    preferred_roles: str = Form(""),
    current_location: str = Form(""),
    preferred_locations: str = Form(""),
    professional_title: str = Form(""),
    professional_titles: str = Form(""),
    linkedin_url: str = Form(""),
    github_url: str = Form(""),
    skills_summary: str = Form(""),
    bio: str = Form(""),
    education_level: str = Form(""),
    course_name: str = Form(""),
    graduation_year: str = Form(""),
):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)

    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    save_profile(
        email=user_email,
        phone=phone.strip(),
        college=college.strip(),
        experience_years=max(0, experience_years),
        preferred_roles=preferred_roles.strip(),
        current_location=current_location.strip(),
        preferred_locations=preferred_locations.strip(),
        professional_title=professional_title.strip(),
        professional_titles=professional_titles.strip(),
        linkedin_url=linkedin_url.strip(),
        github_url=github_url.strip(),
        skills_summary=skills_summary.strip(),
        bio=bio.strip(),
        education_level=education_level.strip(),
        course_name=course_name.strip(),
        graduation_year=graduation_year.strip(),
    )
    return RedirectResponse("/profile?saved=1", status_code=302)
