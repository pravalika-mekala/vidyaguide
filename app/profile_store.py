from app.database import get_db


def get_profile(email: str) -> dict:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT email, phone, college, experience_years, preferred_roles, current_location, preferred_locations,
                   professional_title, professional_titles, linkedin_url, github_url,
                   skills_summary, bio, education_level, course_name, graduation_year,
                   default_resume_file_id, updated_at
            FROM user_profiles
            WHERE email=%s
            """,
            (email,),
        )
        row = cursor.fetchone()
        return row or {
            "email": email,
            "phone": "",
            "college": "",
            "experience_years": 0,
            "preferred_roles": "",
            "current_location": "",
            "preferred_locations": "",
            "professional_title": "",
            "professional_titles": "",
            "linkedin_url": "",
            "github_url": "",
            "skills_summary": "",
            "bio": "",
            "education_level": "",
            "course_name": "",
            "graduation_year": "",
            "default_resume_file_id": None,
        }
    finally:
        cursor.close()
        db.close()


def save_profile(
    email: str,
    phone: str,
    college: str,
    experience_years: float,
    preferred_roles: str,
    current_location: str,
    preferred_locations: str,
    professional_title: str,
    professional_titles: str,
    linkedin_url: str,
    github_url: str,
    skills_summary: str,
    bio: str,
    education_level: str,
    course_name: str,
    graduation_year: str,
):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO user_profiles
            (email, phone, college, experience_years, preferred_roles, current_location, preferred_locations, professional_title,
             professional_titles, linkedin_url, github_url, skills_summary, bio, education_level, course_name, graduation_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                phone=VALUES(phone),
                college=VALUES(college),
                experience_years=VALUES(experience_years),
                preferred_roles=VALUES(preferred_roles),
                current_location=VALUES(current_location),
                preferred_locations=VALUES(preferred_locations),
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
                phone,
                college,
                experience_years,
                preferred_roles,
                current_location,
                preferred_locations,
                professional_title,
                professional_titles,
                linkedin_url,
                github_url,
                skills_summary,
                bio,
                education_level,
                course_name,
                graduation_year,
            ),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def set_default_resume(email: str, file_id: int | None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO user_profiles (email, default_resume_file_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE default_resume_file_id=VALUES(default_resume_file_id)
            """,
            (email, file_id),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()
