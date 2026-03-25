from datetime import datetime
import re

from app.resume_analyzer import clean_text, extract_skills, predict_jobs
from app.settings import get_settings

try:
    import google.generativeai as legacy_genai
except Exception:
    legacy_genai = None

try:
    from google import genai as modern_genai
except Exception:
    modern_genai = None

import logging
logger = logging.getLogger(__name__)

settings = get_settings()
GEMINI_API_KEY = settings.gemini_api_key
GEMINI_MODEL = settings.gemini_model

_model = None
_modern_client = None

if GEMINI_API_KEY and modern_genai:
    try:
        _modern_client = modern_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize modern Gemini client: {e}")
        _modern_client = None

if GEMINI_API_KEY and legacy_genai:
    try:
        legacy_genai.configure(api_key=GEMINI_API_KEY)
        _model = legacy_genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        logger.error(f"Failed to initialize legacy Gemini model: {e}")
        _model = None


TIME_QUERY = "TIME_QUERY"
DATE_QUERY = "DATE_QUERY"
FACTUAL_QUERY = "FACTUAL_QUERY"
TASK_BUILD_QUERY = "TASK_BUILD_QUERY"
GENERAL_CHAT = "GENERAL_CHAT"
GREETING_SMALL_TALK = "GREETING_SMALL_TALK"
EMOTIONAL_PERSONAL = "EMOTIONAL_PERSONAL"
REAL_TIME_QUERY = "REAL_TIME_QUERY"
TECHNICAL_CODING = "TECHNICAL_CODING"
FOLLOW_UP_CONTEXTUAL = "FOLLOW_UP_CONTEXTUAL"


def _job_recommendation_from_text(message: str) -> str:
    normalized = clean_text(message or "")
    skills = extract_skills(normalized)
    jobs = predict_jobs(skills)
    if not jobs:
        return ""
    return "Recommended roles: " + ", ".join(jobs[:4]) + "."


def _classify_intent(message: str) -> str:
    text = (message or "").strip().lower()
    if not text:
        return GENERAL_CHAT

    if any(word in text for word in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "how are you", "how is the day"]):
        return GREETING_SMALL_TALK

    if any(word in text for word in [
        "stressed", "stress", "sad", "upset", "anxious", "worried", "confused",
        "depressed", "tired", "overwhelmed", "i feel", "feeling low"
    ]):
        return EMOTIONAL_PERSONAL

    if re.search(r"\b(time|current time|time now|what'?s the time|tell me the time)\b", text):
        return TIME_QUERY

    if re.search(r"\b(date|today'?s date|current date|what'?s the date|tell me the date|day today)\b", text):
        return DATE_QUERY

    if any(word in text for word in ["continue", "that one", "same one", "same role", "follow up", "what about this", "that one only"]):
        return FOLLOW_UP_CONTEXTUAL

    if any(word in text for word in [
        "code", "python", "java", "javascript", "typescript", "sql", "api", "bug",
        "error", "debug", "function", "class", "algorithm", "react", "fastapi", "html", "css"
    ]):
        return TECHNICAL_CODING

    if any(word in text for word in [
        "build", "create", "make", "implement", "develop", "design",
        "fix", "debug", "roadmap", "steps", "plan", "how to"
    ]):
        return TASK_BUILD_QUERY

    if text.endswith("?") or any(word in text for word in [
        "what", "which", "who", "when", "where", "why", "difference", "explain"
    ]):
        return FACTUAL_QUERY

    return GENERAL_CHAT


def _system_time_reply() -> str:
    return f"Current time is {datetime.now().strftime('%I:%M %p')}"


def _system_date_reply() -> str:
    return f"Today is {datetime.now().strftime('%B %d, %Y')}"


def _intent_hint(intent: str) -> str:
    hints = {
        GREETING_SMALL_TALK: "Respond in a friendly, natural, human-like tone.",
        EMOTIONAL_PERSONAL: "Respond with empathy, support, and calm guidance. Do not sound robotic.",
        TIME_QUERY: "Respond with the real current system time only.",
        DATE_QUERY: "Respond with the real current system date only.",
        FACTUAL_QUERY: "Respond with a concise, accurate answer.",
        TECHNICAL_CODING: "Respond with a structured explanation and include code when it helps.",
        TASK_BUILD_QUERY: "Respond with clear step-by-step guidance.",
        FOLLOW_UP_CONTEXTUAL: "Use only relevant recent context and continue the current topic.",
        GENERAL_CHAT: "Respond naturally and stay relevant to the user's message.",
    }
    return hints.get(intent, hints[GENERAL_CHAT])


def _should_use_history(intent: str, message: str) -> bool:
    if intent == FOLLOW_UP_CONTEXTUAL:
        return True

    text = (message or "").strip().lower()
    contextual_markers = [
        "continue",
        "same",
        "that",
        "this one",
        "those",
        "earlier",
        "previous",
        "last one",
        "what about it",
        "what about that",
    ]
    return any(marker in text for marker in contextual_markers)


def _frontend_language_reply(text: str) -> str:
    if "typescript" in text and "javascript" in text:
        return (
            "Go with TypeScript for frontend projects.\n\n"
            "Reason:\n"
            "- Better autocomplete and type safety\n"
            "- Fewer runtime bugs as projects grow\n"
            "- Strong choice for real-world React apps\n\n"
            "Next steps:\n"
            "1. Learn JavaScript fundamentals\n"
            "2. Move to TypeScript basics\n"
            "3. Build a React project with TypeScript"
        )
    return (
        "Start with JavaScript, then move to TypeScript.\n\n"
        "Reason:\n"
        "- JavaScript is the foundation of frontend\n"
        "- TypeScript becomes much easier after that\n"
        "- This path is practical for real projects\n\n"
        "Next steps:\n"
        "1. Learn JavaScript basics well\n"
        "2. Practice DOM and ES6 concepts\n"
        "3. Move into React with TypeScript"
    )


def _app_build_with_language_reply(text: str) -> str:
    if "c++" in text or "cpp" in text:
        return (
            "Use C++ if your goal is performance-heavy software, desktop apps, or game development.\n\n"
            "Reason:\n"
            "- Strong performance and control\n"
            "- Widely used in systems and game development\n"
            "- Good fit for desktop and embedded applications\n\n"
            "Next steps:\n"
            "1. Learn modern C++ basics\n"
            "2. Practice OOP and STL\n"
            "3. Build a small desktop or systems project"
        )
    if "python" in text:
        return (
            "Use Python if you want to build backend, automation, or AI-driven apps.\n\n"
            "Reason:\n"
            "- Fast to learn and build with\n"
            "- Excellent for APIs, automation, and AI\n"
            "- Strong ecosystem for practical projects\n\n"
            "Next steps:\n"
            "1. Learn Python basics\n"
            "2. Build simple scripts and APIs\n"
            "3. Move to FastAPI or Django projects"
        )
    if "java" in text:
        return (
            "Use Java for backend development and enterprise-style applications.\n\n"
            "Reason:\n"
            "- Strong job demand in backend roles\n"
            "- Great for scalable real-world applications\n"
            "- Widely used in enterprise systems\n\n"
            "Next steps:\n"
            "1. Learn Java basics\n"
            "2. Learn OOP well\n"
            "3. Start backend development with Spring Boot"
        )
    if "javascript" in text or "typescript" in text:
        return (
            "Use JavaScript or TypeScript for web and full-stack app development.\n\n"
            "Reason:\n"
            "- Strong fit for frontend and backend\n"
            "- Practical for full-stack development\n"
            "- Huge ecosystem and job demand\n\n"
            "Next steps:\n"
            "1. Learn JavaScript fundamentals\n"
            "2. Build frontend projects\n"
            "3. Add Node.js or TypeScript for full-stack work"
        )
    return (
        "Choose the language that best matches the kind of app you want to build.\n\n"
        "Reason:\n"
        "- Different languages are better for different goals\n"
        "- Picking the right one makes learning and building easier\n\n"
        "Next steps:\n"
        "1. Decide whether your goal is web, mobile, desktop, or systems\n"
        "2. Pick the language most used in that area\n"
        "3. Build one small project in that stack"
    )


def get_recommended_jobs_from_message(message: str):
    normalized = clean_text(message or "")
    skills = extract_skills(normalized)
    return predict_jobs(skills)[:4]


def _history_as_prompt(history: list[dict] | None) -> str:
    if not history:
        return ""

    lines = []
    for item in history[-8:]:
        role = "User" if item.get("role") == "user" else "Assistant"
        content = str(item.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _profile_as_prompt(profile: dict | None) -> str:
    if not profile or not isinstance(profile, dict):
        return ""
    # Keep only useful, non-sensitive, short fields.
    keys = [
        "professional_title",
        "professional_titles",
        "preferred_roles",
        "experience_years",
        "current_location",
        "preferred_locations",
        "education_level",
        "course_name",
        "graduation_year",
        "skills_summary",
        "bio",
        "linkedin_url",
        "github_url",
    ]
    lines = []
    for k in keys:
        v = profile.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s or s == "0":
            continue
        lines.append(f"- {k.replace('_', ' ').title()}: {s}")
    return "\n".join(lines[:20])


def _fallback_career_reply(message: str, history: list[dict] | None = None) -> str:
    text = (message or "").strip().lower()
    intent = _classify_intent(text)
    previous_context = _history_as_prompt(history).lower() if _should_use_history(intent, text) else ""
    combined_text = f"{previous_context}\n{text}".strip()
    if len(text.split()) <= 4:
        if any(word in text for word in ["hi", "hello", "hey"]):
            return "Hey, I'm here. How can I help?"
        if "how are you" in text:
            return "I'm doing great! How about you?"
        if "how is the day" in text:
            return "It's going well! How's your day going?"
        if any(word in text for word in ["thanks", "thank you"]):
            return "You're welcome."
    if any(k in combined_text for k in ["can we build", "build app", "build apps", "create app", "develop app"]):
        return _app_build_with_language_reply(text)
    if any(k in combined_text for k in ["frontend", "front end"]) and any(k in combined_text for k in ["language", "better", "best", "javascript", "typescript"]):
        return _frontend_language_reply(text)
    if any(k in combined_text for k in ["which", "better", "best"]) and any(k in combined_text for k in ["language", "java", "python", "javascript", "typescript", "c++", "frontend", "backend"]):
        return (
            "Pick Java if your goal is becoming a backend developer.\n\n"
            "Reason:\n"
            "- Strong job demand\n"
            "- Widely used in backend development\n"
            "- Great for building real applications\n\n"
            "Next steps:\n"
            "1. Learn Java basics\n"
            "2. Learn OOP and DSA\n"
            "3. Build backend projects with Spring Boot"
        )
    if any(k in combined_text for k in ["resume", "cv", "ats"]):
        base = (
            "That makes sense. A strong resume usually has measurable achievements, clear project impact, and role-specific skills. "
            "If you want, paste one section and I'll help you rewrite it."
        )
        jobs = _job_recommendation_from_text(message)
        return f"{base} {jobs}".strip()
    if any(k in combined_text for k in ["interview", "hr", "question"]):
        return (
            "Sure. For interviews, use STAR format (Situation, Task, Action, Result) "
            "and prepare 2-3 examples with numbers and outcomes."
        )
    if any(k in combined_text for k in ["skill", "roadmap", "learn"]):
        base = (
            "Good direction. Pick one target role, list 10 core skills from job descriptions, "
            "and build 2 projects that clearly prove those skills."
        )
        jobs = _job_recommendation_from_text(message)
        return f"{base} {jobs}".strip()
    if any(k in combined_text for k in ["job", "apply"]):
        base = (
            "You're on the right path. Customize your resume for each role, keep a weekly tracker, "
            "and prioritize referrals with short tailored notes."
        )
        jobs = _job_recommendation_from_text(message)
        return f"{base} {jobs}".strip()
    return "I'll answer directly based on what you asked."


def ask_ai(message: str, history: list[dict] | None = None, profile: dict | None = None):
    clean_message = (message or "").strip()
    if not clean_message:
        return "Ask me anything."

    intent = _classify_intent(clean_message)
    if intent == TIME_QUERY:
        return _system_time_reply()
    if intent == DATE_QUERY:
        return _system_date_reply()

    conversation_context = _history_as_prompt(history) if _should_use_history(intent, clean_message) else ""
    profile_context = _profile_as_prompt(profile)

    if not _model and not _modern_client:
        return _fallback_career_reply(clean_message, history=history)

    system_prompt = """
You are the "VidyaGuide AI Career Mentor", a specialized assistant for freshers and job seekers.

Your mission is to:
1. Help users understand their career level (Benchmarking).
2. Deeply analyze resumes to uncover skill gaps and weaknesses.
3. Provide clear, actionable steps and structured roadmap for improvement.
4. Recommend suitable jobs based on their unique profile and skills.
5. Act as a dedicated mentor guiding users through every step of getting hired.

Core rules:
- Always match the user's career-focused intent.
- Keep answers relevant to job hunting, technical skills, and career growth.
- Sound encouraging, professional, and mentor-like.
- Provide structured, bite-sized advice that is easy to follow.
- If the user asks about skill gaps or roadmaps, give specific technical or soft skill recommendations.
- When recommending jobs, emphasize how their current skills match the role.

Behavior:
- Classify the user's message to see if they need a roadmap, skill check, or general mentor advice.
- Use the user's profile (if available) to give highly personalized career coaching.
- Never give generic replies; always try to add a career-related "next step" or tip.

Style:
- Warm, expert, and results-oriented.
- Use formatting (bullet points, bold text) to highlight key career actions.
"""

    answer = ""
    try:
        if _modern_client:
            prompt_text = system_prompt
            prompt_text += f"\nDetected intent: {intent}"
            prompt_text += f"\nResponse behavior for this intent: {_intent_hint(intent)}"
            if profile_context:
                prompt_text += f"\nUser profile (may be partial):\n{profile_context}"
            if conversation_context:
                prompt_text += f"\nRecent conversation:\n{conversation_context}"
            model_tag = GEMINI_MODEL
            if not model_tag.startswith("models/"):
                model_tag = f"models/{model_tag}"
            
            response = _modern_client.models.generate_content(
                model=model_tag,
                contents=f"{prompt_text}\nUser: {clean_message}",
            )
            answer = (getattr(response, "text", "") or "").strip()
        elif _model:
            prompt_parts = [system_prompt]
            prompt_parts.append(f"Detected intent: {intent}")
            prompt_parts.append(f"Response behavior for this intent: {_intent_hint(intent)}")
            if profile_context:
                prompt_parts.append(f"User profile (may be partial):\n{profile_context}")
            if conversation_context:
                prompt_parts.append(f"Recent conversation:\n{conversation_context}")
            prompt_parts.append(f"User: {clean_message}")
            response = _model.generate_content(prompt_parts)
            answer = (getattr(response, "text", "") or "").strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return _fallback_career_reply(clean_message, history=history)

    if not answer:
        return _fallback_career_reply(clean_message, history=history)

    jobs_hint = _job_recommendation_from_text(clean_message)
    if jobs_hint:
        return f"{answer}\n\n{jobs_hint}"

    return answer
