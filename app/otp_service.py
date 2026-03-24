import hashlib
import hmac
import random
from datetime import datetime, timedelta

from app.database import get_db
from app.settings import get_settings

settings = get_settings()
OTP_TTL_SECONDS = settings.otp_ttl_seconds
OTP_RESEND_COOLDOWN_SECONDS = settings.otp_resend_cooldown_seconds
OTP_MAX_VERIFY_ATTEMPTS = settings.otp_max_verify_attempts
OTP_MAX_REQUESTS_PER_EMAIL_WINDOW = settings.otp_max_requests_per_email_window
OTP_MAX_REQUESTS_PER_IP_WINDOW = settings.otp_max_requests_per_ip_window
OTP_RATE_WINDOW_SECONDS = settings.otp_rate_window_seconds
OTP_HASH_PEPPER = settings.otp_hash_pepper


def _utcnow() -> datetime:
    return datetime.utcnow()


def _hash_otp(email: str, otp: str) -> str:
    raw = f"{email}:{otp}:{OTP_HASH_PEPPER}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_otp_request(email: str, client_ip: str):
    now = _utcnow()

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM password_reset_ip_rate WHERE ip_address=%s",
            (client_ip,),
        )
        ip_row = cursor.fetchone()
        if ip_row:
            ip_window_start = ip_row["window_start"]
            ip_count = int(ip_row["request_count"])
            if now - ip_window_start > timedelta(seconds=OTP_RATE_WINDOW_SECONDS):
                ip_window_start = now
                ip_count = 0
            if ip_count >= OTP_MAX_REQUESTS_PER_IP_WINDOW:
                return False, None, "Too many OTP requests. Please try again later."
            ip_count += 1
            cursor.execute(
                """
                UPDATE password_reset_ip_rate
                SET request_count=%s, window_start=%s, updated_at=%s
                WHERE ip_address=%s
                """,
                (ip_count, ip_window_start, now, client_ip),
            )
        else:
            cursor.execute(
                """
                INSERT INTO password_reset_ip_rate (ip_address, request_count, window_start, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (client_ip, 1, now, now),
            )

        cursor.execute(
            "SELECT * FROM password_reset_otp WHERE email=%s",
            (email,),
        )
        row = cursor.fetchone()
        request_count = 0
        window_start = now
        if row:
            if now < row["resend_after"]:
                seconds = int((row["resend_after"] - now).total_seconds())
                return False, None, f"Please wait {max(1, seconds)}s before requesting OTP again."

            request_count = int(row["request_count"])
            window_start = row["window_start"]
            if now - window_start > timedelta(seconds=OTP_RATE_WINDOW_SECONDS):
                request_count = 0
                window_start = now

            if request_count >= OTP_MAX_REQUESTS_PER_EMAIL_WINDOW:
                return False, None, "Too many OTP requests for this account. Try later."

        otp = f"{random.randint(0, 999999):06d}"
        otp_hash = _hash_otp(email, otp)
        expires_at = now + timedelta(seconds=OTP_TTL_SECONDS)
        resend_after = now + timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS)
        request_count += 1

        if row:
            cursor.execute(
                """
                UPDATE password_reset_otp
                SET otp_hash=%s, expires_at=%s, resend_after=%s, attempts=0,
                    request_count=%s, window_start=%s, updated_at=%s
                WHERE email=%s
                """,
                (otp_hash, expires_at, resend_after, request_count, window_start, now, email),
            )
        else:
            cursor.execute(
                """
                INSERT INTO password_reset_otp
                (email, otp_hash, expires_at, resend_after, attempts, request_count, window_start, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (email, otp_hash, expires_at, resend_after, 0, request_count, window_start, now),
            )
        db.commit()
        return True, otp, None
    finally:
        cursor.close()
        db.close()


def verify_otp(email: str, otp: str):
    now = _utcnow()

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM password_reset_otp WHERE email=%s",
            (email,),
        )
        row = cursor.fetchone()
        if not row:
            return False, "Invalid OTP."

        if now > row["expires_at"]:
            cursor.execute("DELETE FROM password_reset_otp WHERE email=%s", (email,))
            db.commit()
            return False, "OTP expired. Request a new OTP."

        attempts = int(row["attempts"])
        if attempts >= OTP_MAX_VERIFY_ATTEMPTS:
            return False, "OTP attempts exceeded. Request a new OTP."

        expected_hash = row["otp_hash"]
        provided_hash = _hash_otp(email, otp.strip())
        if not hmac.compare_digest(expected_hash, provided_hash):
            attempts += 1
            cursor.execute(
                "UPDATE password_reset_otp SET attempts=%s, updated_at=%s WHERE email=%s",
                (attempts, now, email),
            )
            db.commit()
            remaining = max(0, OTP_MAX_VERIFY_ATTEMPTS - attempts)
            if remaining == 0:
                return False, "OTP attempts exceeded. Request a new OTP."
            return False, f"Invalid OTP. {remaining} attempts left."

        return True, None
    finally:
        cursor.close()
        db.close()


def clear_otp(email: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM password_reset_otp WHERE email=%s", (email,))
        db.commit()
    finally:
        cursor.close()
        db.close()
