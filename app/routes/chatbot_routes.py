import logging
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.ai_service import ask_ai, get_recommended_jobs_from_message
from app.chat_store import (
    get_chat_history,
    save_chat_turn,
    clear_chat_history,
    get_threads,
    get_active_thread_id,
    set_active_thread,
    new_thread,
    delete_thread,
)
from app.rate_limiter import rate_limiter
from app.request_models import ChatRequest
from app.profile_store import get_profile
from app.settings import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
settings = get_settings()

# --------- CHATBOT PAGE (IMPORTANT) ----------
@router.get("/chatbot", response_class=HTMLResponse)
def chatbot_page(request: Request):
    user_email = (request.session.get("user_email") or "").strip().lower()
    history = get_chat_history(request.session, user_email=user_email)
    threads = get_threads(request.session, user_email=user_email)
    return templates.TemplateResponse(
        "chatbot.html",
        {
            "request": request,
            "chat_history_json": json.dumps(history),
            "has_history": bool(history),
            "chat_threads_json": json.dumps([
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "updated_at": t.get("updated_at"),
                    "preview": (next((i.get("content") for i in (t.get("history") or []) if i.get("role") == "user" and i.get("content")), "") or "")[:80],
                }
                for t in (threads or [])
            ]),
            "active_thread_id": get_active_thread_id(request.session) or (threads[0]["id"] if threads else ""),
        },
    )


def _build_chat_response(request: Request, message: str) -> JSONResponse:
    user_email = (request.session.get("user_email") or "").strip().lower()
    history = get_chat_history(request.session, user_email=user_email)
    profile = get_profile(user_email) if user_email else {}
    reply = ask_ai(message, history=history, profile=profile)
    recommended_jobs = get_recommended_jobs_from_message(message)
    saved_history = save_chat_turn(request.session, message, reply, user_email=user_email)
    return JSONResponse({"reply": reply, "recommended_jobs": recommended_jobs, "history": saved_history})


# --------- CHAT API ----------
@router.post("/chat")
async def chat(request: Request):
    try:
        payload = ChatRequest.from_payload(await request.json())
    except Exception:
        payload = ChatRequest()
    allowed, retry_after = rate_limiter.allow(
        key=f"chat:{request.client.host if request.client else 'unknown'}",
        limit=settings.chat_rate_limit_count,
        window_seconds=settings.chat_rate_limit_window_seconds,
    )
    if not allowed:
        return JSONResponse({"reply": f"Too many chat requests. Please wait {retry_after}s and try again.", "recommended_jobs": []}, status_code=429)
    message = (payload.message or "")[: settings.max_chat_message_chars]
    logger.info("Chat request accepted path=/chat chars=%s", len(message))
    return _build_chat_response(request, message)


# Keep compatibility with existing frontend calls.
@router.post("/ai/chat")
async def ai_chat(request: Request):
    try:
        payload = ChatRequest.from_payload(await request.json())
    except Exception:
        payload = ChatRequest()
    allowed, retry_after = rate_limiter.allow(
        key=f"chat:{request.client.host if request.client else 'unknown'}",
        limit=settings.chat_rate_limit_count,
        window_seconds=settings.chat_rate_limit_window_seconds,
    )
    if not allowed:
        return JSONResponse({"reply": f"Too many chat requests. Please wait {retry_after}s and try again.", "recommended_jobs": []}, status_code=429)
    message = (payload.message or "")[: settings.max_chat_message_chars]
    return _build_chat_response(request, message)


@router.post("/chat/clear")
def clear_chat(request: Request):
    user_email = (request.session.get("user_email") or "").strip().lower()
    clear_chat_history(request.session, user_email=user_email)
    return JSONResponse({"ok": True})


@router.post("/chat/thread/new")
def chat_new_thread(request: Request):
    user_email = (request.session.get("user_email") or "").strip().lower()
    thread = new_thread(request.session, user_email=user_email)
    return JSONResponse({"ok": True, "thread": {"id": thread.get("id"), "title": thread.get("title"), "updated_at": thread.get("updated_at")}, "history": []})


@router.post("/chat/thread/switch")
async def chat_switch_thread(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    thread_id = str(payload.get("thread_id") or "").strip()
    user_email = (request.session.get("user_email") or "").strip().lower()
    thread = set_active_thread(request.session, thread_id, user_email=user_email)
    if not thread:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    history = get_chat_history(request.session, user_email=user_email)
    return JSONResponse({"ok": True, "thread_id": thread_id, "history": history})


@router.post("/chat/thread/delete")
async def chat_delete_thread(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    thread_id = str(payload.get("thread_id") or "").strip()
    user_email = (request.session.get("user_email") or "").strip().lower()
    ok = delete_thread(request.session, thread_id, user_email=user_email)
    threads = get_threads(request.session, user_email=user_email)
    return JSONResponse({"ok": ok, "active_thread_id": get_active_thread_id(request.session) or (threads[0]["id"] if threads else ""), "threads": [
        {"id": t.get("id"), "title": t.get("title"), "updated_at": t.get("updated_at")} for t in (threads or [])
    ]})
