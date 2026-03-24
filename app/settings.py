import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer.") from exc


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_name: str
    session_secret: str
    session_https_only: bool
    session_same_site: str
    session_max_age_seconds: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    db_pool_name: str
    db_pool_size: int
    gemini_api_key: str
    gemini_model: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_sender: str
    otp_console_fallback: bool
    otp_ttl_seconds: int
    otp_resend_cooldown_seconds: int
    otp_max_verify_attempts: int
    otp_max_requests_per_email_window: int
    otp_max_requests_per_ip_window: int
    otp_rate_window_seconds: int
    otp_hash_pepper: str
    admin_emails_raw: str
    max_upload_bytes: int
    max_chat_message_chars: int
    auth_rate_limit_count: int
    auth_rate_limit_window_seconds: int
    chat_rate_limit_count: int
    chat_rate_limit_window_seconds: int
    upload_rate_limit_count: int
    upload_rate_limit_window_seconds: int
    enable_startup_schema_sync: bool

    @property
    def admin_emails(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.admin_emails_raw.split(",")
            if item.strip()
        }

    def validate(self) -> None:
        missing = []
        if not self.session_secret or len(self.session_secret) < 16:
            missing.append("SESSION_SECRET (minimum 16 characters)")
        if not self.db_host:
            missing.append("DB_HOST")
        if not self.db_user:
            missing.append("DB_USER")
        if not self.db_name:
            missing.append("DB_NAME")
        if not self.otp_hash_pepper or len(self.otp_hash_pepper) < 12:
            missing.append("OTP_HASH_PEPPER (minimum 12 characters)")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.smtp_password and not self.otp_console_fallback:
            missing.append("SMTP_PASSWORD (required for OTP unless OTP_CONSOLE_FALLBACK=True)")

        if missing:
            raise RuntimeError(
                "Invalid application configuration. Missing or weak settings: "
                + ", ".join(missing)
            )

        if self.session_same_site not in {"lax", "strict", "none"}:
            raise RuntimeError("SESSION_SAME_SITE must be one of: lax, strict, none.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        app_env=os.getenv("APP_ENV", "development").strip().lower(),
        app_name=os.getenv("APP_NAME", "Vidyaguide").strip() or "Vidyaguide",
        session_secret=os.getenv("SESSION_SECRET", "").strip(),
        session_https_only=_get_bool("SESSION_HTTPS_ONLY", False),
        session_same_site=os.getenv("SESSION_SAME_SITE", "lax").strip().lower() or "lax",
        session_max_age_seconds=_get_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 8),
        db_host=os.getenv("DB_HOST", "").strip(),
        db_port=_get_int("DB_PORT", 3306),
        db_user=os.getenv("DB_USER", "").strip(),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_name=os.getenv("DB_NAME", "").strip(),
        db_pool_name=os.getenv("DB_POOL_NAME", "vidyaguide_pool").strip() or "vidyaguide_pool",
        db_pool_size=_get_int("DB_POOL_SIZE", 5),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip() or "gemini-1.5-flash",
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=_get_int("SMTP_PORT", 587),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip().replace(" ", ""),
        smtp_sender=os.getenv("SMTP_SENDER", "").strip(),
        otp_console_fallback=_get_bool("OTP_CONSOLE_FALLBACK", False),
        otp_ttl_seconds=_get_int("OTP_TTL_SECONDS", 600),
        otp_resend_cooldown_seconds=_get_int("OTP_RESEND_COOLDOWN_SECONDS", 30),
        otp_max_verify_attempts=_get_int("OTP_MAX_VERIFY_ATTEMPTS", 5),
        otp_max_requests_per_email_window=_get_int("OTP_MAX_REQUESTS_PER_EMAIL_WINDOW", 3),
        otp_max_requests_per_ip_window=_get_int("OTP_MAX_REQUESTS_PER_IP_WINDOW", 20),
        otp_rate_window_seconds=_get_int("OTP_RATE_WINDOW_SECONDS", 900),
        otp_hash_pepper=os.getenv("OTP_HASH_PEPPER", "").strip(),
        admin_emails_raw=os.getenv("ADMIN_EMAILS", "").strip(),
        max_upload_bytes=_get_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
        max_chat_message_chars=_get_int("MAX_CHAT_MESSAGE_CHARS", 2000),
        auth_rate_limit_count=_get_int("AUTH_RATE_LIMIT_COUNT", 10),
        auth_rate_limit_window_seconds=_get_int("AUTH_RATE_LIMIT_WINDOW_SECONDS", 300),
        chat_rate_limit_count=_get_int("CHAT_RATE_LIMIT_COUNT", 30),
        chat_rate_limit_window_seconds=_get_int("CHAT_RATE_LIMIT_WINDOW_SECONDS", 300),
        upload_rate_limit_count=_get_int("UPLOAD_RATE_LIMIT_COUNT", 10),
        upload_rate_limit_window_seconds=_get_int("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", 600),
        enable_startup_schema_sync=_get_bool("ENABLE_STARTUP_SCHEMA_SYNC", True),
    )
    settings.validate()
    return settings
