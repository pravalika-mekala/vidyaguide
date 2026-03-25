import os
import re
from collections import Counter

from app.file_storage import write_temp_file, remove_temp_file

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}

SKILLS_DB = {
    "programming": ["python", "java", "c", "c++", "javascript", "typescript", "sql"],
    "web": ["html", "css", "react", "angular", "node", "express", "rest api", "fastapi", "django"],
    "data": ["pandas", "numpy", "matplotlib", "power bi", "tableau", "machine learning", "deep learning", "tensorflow", "scikit"],
    "tools": ["git", "github", "docker", "linux", "aws", "azure", "gcp", "jira"],
    "database": ["mysql", "mongodb", "postgresql", "redis"],
}

JOB_ROLES = {
    "Software Developer": ["python", "java", "c++", "sql", "git", "oop"],
    "Web Developer": ["html", "css", "javascript", "react", "node", "rest api"],
    "Backend Developer": ["python", "fastapi", "django", "node", "sql", "api", "database"],
    "Data Analyst": ["python", "pandas", "numpy", "sql", "tableau", "power bi"],
    "ML Engineer": ["machine learning", "tensorflow", "python", "deep learning", "scikit"],
}

SECTION_KEYWORDS = {
    "summary": ["summary", "profile", "objective"],
    "experience": ["experience", "work history", "employment"],
    "projects": ["projects", "project"],
    "skills": ["skills", "technical skills", "core skills"],
    "education": ["education", "academic"],
    "certifications": ["certification", "certifications", "licenses"],
}

ACTION_VERBS = {
    "built", "developed", "implemented", "optimized", "designed", "led", "delivered",
    "improved", "automated", "analyzed", "created", "deployed", "reduced", "increased",
}


def _read_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(file_path)
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages)
    except Exception:
        return ""


def _read_docx(file_path: str) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""

    try:
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception:
        return ""


def extract_text_from_file(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return "", ext

    if ext == ".txt":
        return _read_txt(file_path), ext
    if ext == ".pdf":
        return _read_pdf(file_path), ext
    if ext == ".docx":
        return _read_docx(file_path), ext

    return "", ext


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9@+.#:/ -]", " ", text)).strip().lower()


def extract_candidate_name(raw_text: str):
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if "@" in cleaned or "linkedin.com" in cleaned.lower() or "github.com" in cleaned.lower():
            continue
        if len(cleaned.split()) < 2 or len(cleaned.split()) > 5:
            continue
        if re.search(r"\d", cleaned):
            continue
        return cleaned
    return None


def extract_contact_details(raw_text: str):
    # Email: pick the first plausible email, ignore obvious placeholders
    email_matches = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw_text)
    email = None
    for candidate in email_matches:
        lowered = candidate.lower()
        if "example.com" in lowered or "no-reply" in lowered or "noreply" in lowered:
            continue
        email = candidate
        break

    # Phone: ensure at least 10 digits, tolerate separators and country code
    phone_matches = re.findall(
        r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}",
        raw_text,
    )
    phone = None
    for candidate in phone_matches:
        digits = re.sub(r"\D", "", candidate)
        if len(digits) >= 10:
            phone = candidate
            break

    # LinkedIn & GitHub: normalise and strip trailing punctuation
    def _pick_profile(pattern: str):
        matches = re.findall(pattern, raw_text, flags=re.IGNORECASE)
        if not matches:
            return None
        url = str(matches[0]).strip().rstrip(").,;")
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url.lstrip("/")
        return url

    linkedin = _pick_profile(r"(?:https?://)?(?:www\.)?linkedin\.com/[^\s]+")
    github = _pick_profile(r"(?:https?://)?(?:www\.)?github\.com/[^\s]+")

    return {
        "name": extract_candidate_name(raw_text),
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
    }


def extract_sections(text: str):
    found = {}
    for section, keys in SECTION_KEYWORDS.items():
        found[section] = any(k in text for k in keys)
    return found


def extract_skills(text: str):
    found = set()
    for skills in SKILLS_DB.values():
        for skill in skills:
            if skill in text:
                found.add(skill)
    return sorted(found)


def predict_jobs(skills):
    matched_jobs = []
    skill_set = set(skills)
    for role, required in JOB_ROLES.items():
        overlap = len([s for s in required if s in skill_set])
        if overlap >= 2:
            matched_jobs.append((role, overlap))
    matched_jobs.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in matched_jobs[:5]]


def calculate_ats_score(raw_text: str, normalized_text: str, skills, sections, contact):
    score = 0
    tips = []

    # Contact completeness (15)
    if contact["email"]:
        score += 6
    else:
        tips.append("Add a professional email address in the header.")

    if contact["name"]:
        score += 3
    else:
        tips.append("Keep your full name clearly visible at the top of the resume.")

    if contact["phone"]:
        score += 4
    else:
        tips.append("Add a phone number so recruiters can contact you quickly.")

    if contact["linkedin"] or contact["github"]:
        score += 5
    else:
        tips.append("Add LinkedIn or GitHub profile links.")

    # Section coverage (35)
    section_weights = {
        "summary": 5,
        "experience": 8,
        "projects": 8,
        "skills": 5,
        "education": 5,
        "certifications": 4,
    }
    for section, weight in section_weights.items():
        if sections.get(section):
            score += weight
        else:
            tips.append(f"Add a clear '{section.title()}' section.")

    # Skills richness (30)
    unique_skill_count = len(skills)
    score += min(unique_skill_count * 2, 30)
    if unique_skill_count < 8:
        tips.append("Include more role-specific technical skills from target job descriptions.")

    # Achievement quality (20)
    words = re.findall(r"[a-zA-Z]+", normalized_text)
    word_counter = Counter(words)
    action_hits = sum(word_counter.get(v, 0) for v in ACTION_VERBS)
    number_hits = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", raw_text))

    score += min(action_hits, 10)
    score += min(number_hits, 10)

    if action_hits < 4:
        tips.append("Use strong action verbs (built, optimized, delivered, automated) in bullet points.")
    if number_hits < 4:
        tips.append("Quantify impact with numbers (%, time saved, users served, revenue impact).")

    priority_tips = list(dict.fromkeys(tips))
    end_tips = [
        "Tailor this resume for one target role before applying.",
        "Keep the strongest two projects and quantify the impact clearly.",
        "Review contact details and profile links before every application.",
    ]
    for item in end_tips:
        if item not in priority_tips:
            priority_tips.append(item)

    return min(score, 100), priority_tips


def analyze_resume(file_path: str):
    text, file_type = extract_text_from_file(file_path)

    if not text or len(text.strip()) < 80:
        return {
            "score": 0,
            "skills": [],
            "tips": [
                "Could not read enough resume content. Upload a text-selectable PDF, DOCX, or TXT file.",
                "If you uploaded a scanned image PDF, convert it to selectable text first.",
            ],
            "jobs": [],
            "contact": {},
            "sections": {},
            "word_count": 0,
            "file_type": file_type,
            "career_level": "Unknown",
            "skill_gaps": [],
            "roadmap": []
        }

    normalized = clean_text(text)
    skills = extract_skills(normalized)
    contact = extract_contact_details(text)
    sections = extract_sections(normalized)
    jobs = predict_jobs(skills)
    score, tips = calculate_ats_score(text, normalized, skills, sections, contact)

    # 1. Career Level Estimation
    # Simple heuristic: word count and skill count
    word_count = len(re.findall(r"\w+", text))
    unique_skills = len(skills)
    
    # Check for experience keywords or number of years
    experience_matches = re.findall(r"(\d+)\+?\s*(?:years?|yrs?)\s+experience", normalized)
    years = max([int(y) for y in experience_matches] + [0])
    
    if years == 0 and unique_skills < 10:
        career_level = "Fresher"
    elif years < 3:
        career_level = "Entry Level / Junior"
    elif years < 7:
        career_level = "Mid-Level Professional"
    else:
        career_level = "Senior / Expert"

    # 2. Skill Gap Analysis
    # Compare with the top predicted job role's requirements
    skill_gaps = []
    if jobs:
        target_role = jobs[0]
        required_skills = JOB_ROLES.get(target_role, [])
        skill_gaps = [s for s in required_skills if s not in set(skills)]

    # 3. Roadmap Generation (Internal)
    # This will be used by the frontend to fetch from ROLE_LEARNING_PLAN
    # or we can attach a baseline roadmap here.
    roadmap = []
    if jobs:
        from app.main import ROLE_LEARNING_PLAN
        roadmap_data = ROLE_LEARNING_PLAN.get(jobs[0].lower().replace(" ", ""), {}).get("course_structure", [])
        for step in roadmap_data:
            roadmap.append({
                "phase": step[0],
                "topics": step[1],
                "duration": step[2]
            })

    return {
        "score": score,
        "skills": skills,
        "tips": tips,
        "jobs": jobs,
        "contact": contact,
        "sections": sections,
        "word_count": word_count,
        "file_type": file_type,
        "career_level": career_level,
        "skill_gaps": skill_gaps,
        "roadmap": roadmap
    }


def analyze_resume_bytes(file_bytes: bytes, extension: str):
    ext = (extension or "").lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {
            "score": 0,
            "skills": [],
            "tips": [
                "Unsupported file type. Please upload PDF, DOCX, or TXT resume."
            ],
            "jobs": [],
            "contact": {},
            "sections": {},
            "word_count": 0,
            "file_type": ext or "unknown",
        }

    temp_path = write_temp_file(file_bytes, ext)
    try:
        return analyze_resume(temp_path)
    finally:
        remove_temp_file(temp_path)
