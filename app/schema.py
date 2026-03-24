from mysql.connector import Error as MySQLError

from app.database import get_db


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    return cursor.fetchone() is not None


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def ensure_application_schema() -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_profiles (
                email VARCHAR(255) PRIMARY KEY,
                target_role VARCHAR(50) NOT NULL DEFAULT 'backend'
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_task_progress (
                email VARCHAR(255) NOT NULL,
                progress_date DATE NOT NULL,
                completed TINYINT(1) NOT NULL DEFAULT 0,
                PRIMARY KEY (email, progress_date)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_email VARCHAR(255),
                original_filename VARCHAR(255) NOT NULL,
                content_type VARCHAR(255),
                extension VARCHAR(20),
                purpose VARCHAR(100) NOT NULL DEFAULT 'resume',
                category VARCHAR(50) NOT NULL DEFAULT 'general',
                file_size INT NOT NULL,
                file_data LONGBLOB NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_otp (
                email VARCHAR(255) PRIMARY KEY,
                otp_hash VARCHAR(64) NOT NULL,
                expires_at DATETIME NOT NULL,
                resend_after DATETIME NOT NULL,
                attempts INT NOT NULL DEFAULT 0,
                request_count INT NOT NULL DEFAULT 0,
                window_start DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_ip_rate (
                ip_address VARCHAR(64) PRIMARY KEY,
                request_count INT NOT NULL DEFAULT 0,
                window_start DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS signup_pending (
                email VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                current_location VARCHAR(255),
                education_level VARCHAR(30),
                course_name VARCHAR(255),
                graduation_year VARCHAR(4),
                college VARCHAR(255),
                experience_years DECIMAL(4,1) DEFAULT 0,
                preferred_roles TEXT,
                preferred_locations VARCHAR(500),
                professional_title VARCHAR(255),
                professional_titles TEXT,
                linkedin_url VARCHAR(500),
                github_url VARCHAR(500),
                skills_summary TEXT,
                bio TEXT,
                default_resume_file_id BIGINT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                email VARCHAR(255) PRIMARY KEY,
                phone VARCHAR(50),
                college VARCHAR(255),
                experience_years DECIMAL(4,1) DEFAULT 0,
                preferred_roles TEXT,
                current_location VARCHAR(255),
                preferred_locations VARCHAR(500),
                professional_title VARCHAR(255),
                professional_titles TEXT,
                linkedin_url VARCHAR(500),
                github_url VARCHAR(500),
                skills_summary TEXT,
                bio TEXT,
                default_resume_file_id BIGINT NULL,
                education_level VARCHAR(30),
                course_name VARCHAR(255),
                graduation_year VARCHAR(4),
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )

        _ensure_column(cursor, "signup_pending", "professional_titles", "professional_titles TEXT")
        _ensure_column(cursor, "signup_pending", "linkedin_url", "linkedin_url VARCHAR(500)")
        _ensure_column(cursor, "signup_pending", "github_url", "github_url VARCHAR(500)")
        _ensure_column(cursor, "signup_pending", "preferred_roles", "preferred_roles TEXT")
        _ensure_column(cursor, "signup_pending", "default_resume_file_id", "default_resume_file_id BIGINT NULL")
        _ensure_column(cursor, "user_profiles", "professional_titles", "professional_titles TEXT")
        _ensure_column(cursor, "user_profiles", "linkedin_url", "linkedin_url VARCHAR(500)")
        _ensure_column(cursor, "user_profiles", "github_url", "github_url VARCHAR(500)")
        _ensure_column(cursor, "user_profiles", "preferred_roles", "preferred_roles TEXT")
        _ensure_column(cursor, "user_profiles", "default_resume_file_id", "default_resume_file_id BIGINT NULL")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job_applications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50) NOT NULL,
                linkedin_url VARCHAR(500),
                github_url VARCHAR(500),
                job_title VARCHAR(255) NOT NULL,
                company VARCHAR(255),
                location VARCHAR(255),
                detected_skills TEXT,
                resume_filename VARCHAR(255),
                resume_file_id BIGINT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_threads (
                email VARCHAR(255) NOT NULL,
                thread_id VARCHAR(64) NOT NULL,
                title VARCHAR(255) NOT NULL DEFAULT 'New chat',
                history_json LONGTEXT NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (email, thread_id)
            )
            """
        )

        try:
            if not _column_exists(cursor, "users", "is_active"):
                cursor.execute(
                    "ALTER TABLE users ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1"
                )
        except MySQLError as exc:
            if getattr(exc, "errno", None) != 1146:
                raise

        db.commit()
    finally:
        cursor.close()
        db.close()
