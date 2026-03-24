import json
import time
import uuid

from app.database import get_db

CHAT_SESSION_KEY = "chat_history"
CHAT_THREADS_KEY = "chat_threads"
CHAT_ACTIVE_THREAD_KEY = "chat_active_thread_id"

CHAT_MAX_MESSAGES = 20
CHAT_MAX_THREADS = 30
CHAT_MIN_MESSAGES_TO_KEEP_THREAD = 2


def _now_ts() -> int:
    return int(time.time())


def _make_thread_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def _sanitize_history(value) -> list[dict]:
    history = value or []
    if not isinstance(history, list):
        return []
    output: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            output.append({"role": role, "content": content})
    return output[-CHAT_MAX_MESSAGES:]


def _thread_title_from_history(history: list[dict]) -> str:
    for item in history:
        if item.get("role") == "user" and item.get("content"):
            title = str(item["content"]).strip()
            title = " ".join(title.split())
            return (title[:40] + "...") if len(title) > 40 else title
    return "Untitled chat"


def _sanitize_threads(value) -> list[dict]:
    threads = value or []
    if not isinstance(threads, list):
        return []
    output: list[dict] = []
    for t in threads:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id", "")).strip()
        if not tid:
            continue
        title = str(t.get("title", "")).strip() or "Untitled chat"
        updated_at = int(t.get("updated_at") or 0)
        history = _sanitize_history(t.get("history"))
        output.append({"id": tid, "title": title, "updated_at": updated_at, "history": history})
    output.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return output[:CHAT_MAX_THREADS]


def _session_threads(session) -> list[dict]:
    return _sanitize_threads(session.get(CHAT_THREADS_KEY))


def _is_meaningful_thread(thread: dict | None) -> bool:
    if not isinstance(thread, dict):
        return False
    history = _sanitize_history(thread.get("history"))
    return len(history) >= CHAT_MIN_MESSAGES_TO_KEEP_THREAD


def _load_db_threads(email: str) -> list[dict]:
    normalized = _normalize_email(email)
    if not normalized:
        return []

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        try:
            cursor.execute(
                """
                SELECT thread_id, title, history_json, UNIX_TIMESTAMP(updated_at) AS updated_ts
                FROM chat_threads
                WHERE email=%s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (normalized, CHAT_MAX_THREADS),
            )
        except Exception:
            return []

        rows = cursor.fetchall() or []
        threads: list[dict] = []
        for row in rows:
            try:
                history = json.loads(row.get("history_json") or "[]")
            except json.JSONDecodeError:
                history = []
            threads.append({
                "id": str(row.get("thread_id") or "").strip(),
                "title": str(row.get("title") or "Untitled chat").strip() or "Untitled chat",
                "updated_at": int(row.get("updated_ts") or 0),
                "history": _sanitize_history(history),
            })
        return _sanitize_threads(threads)
    finally:
        cursor.close()
        db.close()


def _save_db_threads(email: str, threads: list[dict]) -> None:
    normalized = _normalize_email(email)
    if not normalized:
        return

    cleaned = [thread for thread in _sanitize_threads(threads) if _is_meaningful_thread(thread)]
    db = get_db()
    cursor = db.cursor()
    try:
        try:
            cursor.execute("DELETE FROM chat_threads WHERE email=%s", (normalized,))
            for thread in cleaned:
                cursor.execute(
                    """
                    INSERT INTO chat_threads (email, thread_id, title, history_json, updated_at)
                    VALUES (%s, %s, %s, %s, FROM_UNIXTIME(%s))
                    """,
                    (
                        normalized,
                        thread["id"],
                        thread.get("title") or "Untitled chat",
                        json.dumps(_sanitize_history(thread.get("history")), ensure_ascii=True),
                        int(thread.get("updated_at") or _now_ts()),
                    ),
                )
            db.commit()
        except Exception:
            db.rollback()
    finally:
        cursor.close()
        db.close()


def _sync_session_threads(session, threads: list[dict], active_thread_id: str | None = None) -> list[dict]:
    cleaned = _sanitize_threads(threads)
    session[CHAT_THREADS_KEY] = cleaned
    if cleaned:
        session[CHAT_ACTIVE_THREAD_KEY] = active_thread_id or get_active_thread_id(session) or cleaned[0]["id"]
    else:
        session.pop(CHAT_ACTIVE_THREAD_KEY, None)
    session.pop(CHAT_SESSION_KEY, None)
    return cleaned


def get_threads(session, user_email: str | None = None) -> list[dict]:
    normalized = _normalize_email(user_email)
    if normalized:
        db_threads = _load_db_threads(normalized)
        session_threads = _session_threads(session)
        draft_threads = [
            thread for thread in session_threads
            if not _is_meaningful_thread(thread) and all(thread.get("id") != db_thread.get("id") for db_thread in db_threads)
        ]
        if db_threads or draft_threads:
            merged = draft_threads + db_threads
            active_id = get_active_thread_id(session)
            if active_id and any(thread.get("id") == active_id for thread in merged):
                return _sync_session_threads(session, merged, active_id)
            return _sync_session_threads(session, merged)

    threads = _session_threads(session)
    if threads:
        return threads

    legacy = _sanitize_history(session.get(CHAT_SESSION_KEY))
    if not legacy:
        tid = _make_thread_id()
        threads = [{"id": tid, "title": "Untitled chat", "updated_at": _now_ts(), "history": []}]
        _sync_session_threads(session, threads, tid)
        return threads

    tid = _make_thread_id()
    threads = [{
        "id": tid,
        "title": _thread_title_from_history(legacy),
        "updated_at": _now_ts(),
        "history": legacy,
    }]
    _sync_session_threads(session, threads, tid)
    if normalized:
        _save_db_threads(normalized, threads)
    return threads


def get_active_thread_id(session) -> str | None:
    tid = session.get(CHAT_ACTIVE_THREAD_KEY)
    if not tid:
        return None
    return str(tid).strip() or None


def get_active_thread(session, user_email: str | None = None) -> dict | None:
    threads = get_threads(session, user_email=user_email)
    active_id = get_active_thread_id(session) or (threads[0]["id"] if threads else None)
    for thread in threads:
        if thread["id"] == active_id:
            return thread
    return threads[0] if threads else None


def get_chat_history(session, user_email: str | None = None) -> list[dict]:
    active = get_active_thread(session, user_email=user_email)
    if active:
        return _sanitize_history(active.get("history"))
    return _sanitize_history(session.get(CHAT_SESSION_KEY))


def set_active_thread(session, thread_id: str, user_email: str | None = None) -> dict | None:
    thread_id = str(thread_id or "").strip()
    if not thread_id:
        return None
    threads = get_threads(session, user_email=user_email)
    for thread in threads:
        if thread["id"] == thread_id:
            session[CHAT_ACTIVE_THREAD_KEY] = thread_id
            return thread
    return None


def new_thread(session, user_email: str | None = None) -> dict:
    active = get_active_thread(session, user_email=user_email)
    if active and not _is_meaningful_thread(active):
        session[CHAT_ACTIVE_THREAD_KEY] = active["id"]
        return active

    threads = get_threads(session, user_email=user_email)
    tid = _make_thread_id()
    thread = {"id": tid, "title": "Untitled chat", "updated_at": _now_ts(), "history": []}
    threads.insert(0, thread)
    threads = _sync_session_threads(session, threads[:CHAT_MAX_THREADS], tid)
    normalized = _normalize_email(user_email)
    if normalized and any(_is_meaningful_thread(item) for item in threads):
        _save_db_threads(normalized, threads)
    return thread


def save_chat_turn(session, user_message: str, assistant_message: str, user_email: str | None = None) -> list[dict]:
    threads = get_threads(session, user_email=user_email)
    active = get_active_thread(session, user_email=user_email)
    if not active:
        active = new_thread(session, user_email=user_email)
        threads = get_threads(session, user_email=user_email)

    history = _sanitize_history(active.get("history"))
    if user_message.strip():
        history.append({"role": "user", "content": user_message.strip()})
    if assistant_message.strip():
        history.append({"role": "assistant", "content": assistant_message.strip()})
    history = history[-CHAT_MAX_MESSAGES:]

    active["history"] = history
    active["updated_at"] = _now_ts()
    active["title"] = active.get("title") or _thread_title_from_history(history)
    if (active.get("title") or "").strip() in {"New chat", "Untitled chat", ""}:
        active["title"] = _thread_title_from_history(history)

    threads = [thread for thread in threads if thread.get("id") != active.get("id")]
    threads.insert(0, active)
    threads = _sync_session_threads(session, threads[:CHAT_MAX_THREADS], active["id"])

    normalized = _normalize_email(user_email)
    if normalized:
        _save_db_threads(normalized, threads)
    return history


def clear_chat_history(session, user_email: str | None = None) -> None:
    active = get_active_thread(session, user_email=user_email)
    if active:
        active["history"] = []
        active["updated_at"] = _now_ts()
        active["title"] = "Untitled chat"
        threads = get_threads(session, user_email=user_email)
        threads = [thread for thread in threads if thread.get("id") != active.get("id")]
        threads.insert(0, active)
        threads = _sync_session_threads(session, threads[:CHAT_MAX_THREADS], active["id"])
        normalized = _normalize_email(user_email)
        if normalized:
            _save_db_threads(normalized, threads)
    session.pop(CHAT_SESSION_KEY, None)


def delete_thread(session, thread_id: str, user_email: str | None = None) -> bool:
    thread_id = str(thread_id or "").strip()
    if not thread_id:
        return False
    threads = get_threads(session, user_email=user_email)
    if len(threads) <= 1:
        clear_chat_history(session, user_email=user_email)
        return True
    remaining = [thread for thread in threads if thread.get("id") != thread_id]
    if len(remaining) == len(threads):
        return False
    if not remaining:
        remaining = [{"id": _make_thread_id(), "title": "Untitled chat", "updated_at": _now_ts(), "history": []}]
    _sync_session_threads(session, remaining, remaining[0]["id"])
    normalized = _normalize_email(user_email)
    if normalized:
        _save_db_threads(normalized, remaining)
    return True
