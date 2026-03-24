import logging
import os
import time
from datetime import date

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.routes import auth_routes, resume_routes, chatbot_routes, job_routes, profile_routes, material_routes, admin_routes
from app.database import get_db, init_db_pool
from app.logging_config import configure_logging
from app.schema import ensure_application_schema
from app.settings import get_settings

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title=settings.app_name)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


def static_asset_url(request: Request, asset_path: str) -> str:
    relative_path = asset_path.lstrip("/").replace("/", os.sep)
    full_path = os.path.join("static", relative_path)
    version = "0"
    try:
        version = str(int(os.path.getmtime(full_path)))
    except OSError:
        pass
    return str(request.url_for("static", path=asset_path)).rstrip("/") + f"?v={version}"


templates.env.globals["static_asset_url"] = static_asset_url

# Session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.session_https_only,
    same_site=settings.session_same_site,
    max_age=settings.session_max_age_seconds,
)

DAILY_UPDATES = [
    "DSA focus: Solve 2 array problems and 1 binary search problem.",
    "Interview focus: Practice 3 HR answers using STAR format.",
    "Communication focus: Record a 2-minute self-introduction.",
    "System design focus: Design a URL shortener at high level.",
    "Mock round focus: Run one timed coding interview simulation.",
    "Project focus: Add one measurable resume bullet to a project.",
    "Recovery focus: Reflect for 15 minutes and plan next week.",
]

ROLE_OPTIONS = [
    ("backend", "Backend Developer"),
    ("frontend", "Frontend Developer"),
    ("fullstack", "Full Stack Developer"),
    ("data", "Data Analyst"),
]

ROLE_LEARNING_PLAN = {
    "backend": {
        "interview_materials": [
            "Core Python/Java/API interview questions with practical examples.",
            "Database indexing, transactions, and scaling interview scenarios.",
            "System design basics: caching, queues, load balancing.",
        ],
        "dsa_materials": [
            "Arrays, hashing, sorting, binary search.",
            "Linked lists, stacks, queues, recursion.",
            "Trees, graphs, dynamic programming fundamentals.",
        ],
        "softskills_management": [
            "Explain architecture in 90 seconds with clarity.",
            "Practice conflict-resolution examples from team projects.",
            "Use STAR format for ownership and impact answers.",
        ],
        "demo_interviews": [
            "5-minute breathing + 20-minute timed coding mock.",
            "One backend API design mock interview with review.",
            "Reflect on one mistake and one strength after each mock.",
        ],
        "course_structure": [
            ("Foundation", "Python/Java, SQL, API basics, Git workflows", "Weeks 1-4"),
            ("Interview Readiness", "DSA patterns, backend LLD, behavioral prep", "Weeks 5-8"),
            ("Placement Sprint", "Mock interviews, company-focused prep, applications", "Weeks 9-12"),
        ],
    },
    "frontend": {
        "interview_materials": [
            "HTML/CSS/JS deep questions and browser behavior topics.",
            "React component architecture and state management scenarios.",
            "Web performance and accessibility interview checklists.",
        ],
        "dsa_materials": [
            "Arrays, strings, hash maps, sliding window.",
            "Stacks/queues and common UI algorithm questions.",
            "Trees/graphs and recursion for interview readiness.",
        ],
        "softskills_management": [
            "Explain UI tradeoffs and user-first decisions.",
            "Practice design-feedback conversation techniques.",
            "Present project outcomes with measurable impact.",
        ],
        "demo_interviews": [
            "Short mock on DOM/event loop and component lifecycle.",
            "Timed coding round on UI-focused problems.",
            "Anxiety reset: breathe, reframe, retry with checklist.",
        ],
        "course_structure": [
            ("Foundation", "HTML/CSS/JS, responsive design, Git", "Weeks 1-4"),
            ("Interview Readiness", "React patterns, performance, DSA core", "Weeks 5-8"),
            ("Placement Sprint", "Portfolio polish, mocks, applications", "Weeks 9-12"),
        ],
    },
    "fullstack": {
        "interview_materials": [
            "End-to-end interview set: frontend + backend + DB.",
            "API contracts, auth flows, and deployment Q&A.",
            "System design for complete web applications.",
        ],
        "dsa_materials": [
            "Core patterns: arrays, hashing, two pointers.",
            "Trees, graphs, recursion, dynamic programming basics.",
            "Mix of frontend and backend coding interview tasks.",
        ],
        "softskills_management": [
            "Practice clear handoff communication across teams.",
            "Structure project demos around problem-solution-impact.",
            "Handle clarifying questions with concise responses.",
        ],
        "demo_interviews": [
            "One coding mock + one architecture discussion mock.",
            "Pressure simulation: solve while speaking your approach.",
            "Post-mock anxiety journal and improvement plan.",
        ],
        "course_structure": [
            ("Foundation", "Web fundamentals, backend APIs, SQL/NoSQL", "Weeks 1-4"),
            ("Interview Readiness", "DSA + LLD + full-stack case studies", "Weeks 5-8"),
            ("Placement Sprint", "Mock loops, project storytelling, applications", "Weeks 9-12"),
        ],
    },
    "data": {
        "interview_materials": [
            "SQL, statistics, and analytics case interview bank.",
            "Data cleaning, EDA, and dashboard storytelling questions.",
            "Business metric interpretation and stakeholder scenarios.",
        ],
        "dsa_materials": [
            "Arrays, sorting, binary search, hash maps.",
            "SQL query patterns and optimization basics.",
            "Probability/statistics problem practice.",
        ],
        "softskills_management": [
            "Explain insights for non-technical audiences.",
            "Practice concise data storytelling with charts.",
            "Improve stakeholder communication and prioritization.",
        ],
        "demo_interviews": [
            "Mock SQL round with timed query writing.",
            "Case-study mock on business impact analysis.",
            "Breathing + reflection protocol before and after mocks.",
        ],
        "course_structure": [
            ("Foundation", "Excel/SQL/Python, statistics basics", "Weeks 1-4"),
            ("Interview Readiness", "Case studies, dashboards, SQL depth", "Weeks 5-8"),
            ("Placement Sprint", "Portfolio, mock rounds, targeted applications", "Weeks 9-12"),
        ],
    },
}

def _get_user_role(email: str) -> str:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT target_role FROM learning_profiles WHERE email=%s", (email,))
        row = cursor.fetchone()
        role = (row[0] if row else "backend") or "backend"
        return role if role in ROLE_LEARNING_PLAN else "backend"
    finally:
        cursor.close()
        db.close()


def _set_user_role(email: str, role: str):
    normalized = role if role in ROLE_LEARNING_PLAN else "backend"
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO learning_profiles (email, target_role)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE target_role=VALUES(target_role)
        """, (email, normalized))
        db.commit()
    finally:
        cursor.close()
        db.close()


def _is_daily_task_completed(email: str, today: date) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT completed FROM daily_task_progress WHERE email=%s AND progress_date=%s",
            (email, today),
        )
        row = cursor.fetchone()
        return bool(row and row[0])
    finally:
        cursor.close()
        db.close()


def _set_daily_task_completed(email: str, today: date, completed: bool):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO daily_task_progress (email, progress_date, completed)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE completed=VALUES(completed)
        """, (email, today, int(completed)))
        db.commit()
    finally:
        cursor.close()
        db.close()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/login")

    # Older sessions may still contain email.
    if isinstance(user, str) and "@" in user:
        user = user.split("@", 1)[0]

    request.session["admin_mode"] = False

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
    })


@app.get("/learning-hub", response_class=HTMLResponse)
def learning_hub(request: Request):
    user = request.session.get("user")
    user_email = (request.session.get("user_email") or "").strip().lower()

    if not user:
        return RedirectResponse("/login")

    if isinstance(user, str) and "@" in user:
        if not user_email:
            user_email = user.strip().lower()
        user = user.split("@", 1)[0]

    if not user_email:
        return RedirectResponse("/login", status_code=302)

    today = date.today()
    daily_update = DAILY_UPDATES[today.weekday()]
    selected_role = _get_user_role(user_email)
    role_plan = ROLE_LEARNING_PLAN[selected_role]
    task_done = _is_daily_task_completed(user_email, today)

    return templates.TemplateResponse("learning_hub.html", {
        "request": request,
        "user": user,
        "selected_role": selected_role,
        "role_options": ROLE_OPTIONS,
        "role_label": dict(ROLE_OPTIONS).get(selected_role, "Backend Developer"),
        "interview_materials": role_plan["interview_materials"],
        "dsa_materials": role_plan["dsa_materials"],
        "softskills_management": role_plan["softskills_management"],
        "demo_interviews": role_plan["demo_interviews"],
        "course_structure": role_plan["course_structure"],
        "today_label": today.strftime("%B %d, %Y"),
        "daily_update": daily_update,
        "task_done": task_done,
    })


@app.post("/learning-hub/role")
def update_learning_role(request: Request, role: str = Form(...)):
    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    _set_user_role(user_email, role.strip().lower())
    return RedirectResponse("/learning-hub", status_code=302)


@app.post("/learning-hub/daily-task")
def update_daily_task(request: Request, action: str = Form("complete")):
    user_email = (request.session.get("user_email") or "").strip().lower()
    if not user_email:
        return RedirectResponse("/login", status_code=302)

    completed = action.strip().lower() == "complete"
    _set_daily_task_completed(user_email, date.today(), completed)
    return RedirectResponse("/learning-hub", status_code=302)


app.include_router(auth_routes.router)
app.include_router(chatbot_routes.router)
app.include_router(resume_routes.router)
app.include_router(job_routes.router)
app.include_router(profile_routes.router)
app.include_router(material_routes.router)
app.include_router(admin_routes.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.on_event("startup")
def startup_event():
    init_db_pool()
    if settings.enable_startup_schema_sync:
        ensure_application_schema()
    logger.info("Application startup complete for env=%s", settings.app_env)


@app.middleware("http")
async def add_operational_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req-{int(time.time() * 1000)}"
    request.state.request_id = request_id
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
