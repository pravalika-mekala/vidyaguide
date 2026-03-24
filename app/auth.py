from passlib.hash import bcrypt
from mysql.connector import Error as MySQLError
from app.database import get_db


# CREATE ACCOUNT
def create_user(name, email, password):
    db = get_db()
    cursor = db.cursor()

    try:
        hashed_password = bcrypt.hash(password)
        query = """
        INSERT INTO users (name, email, password_hash)
        VALUES (%s, %s, %s)
        """
        values = (name, email, hashed_password)
        cursor.execute(query, values)
        db.commit()
        return True, None
    except MySQLError as exc:
        # 1062 is duplicate key/email in MySQL
        if getattr(exc, "errno", None) == 1062:
            return False, "An account with this email already exists."
        return False, "Unable to create account right now. Please try again."
    finally:
        cursor.close()
        db.close()


def create_user_with_hash(name, email, password_hash):
    db = get_db()
    cursor = db.cursor()
    try:
        query = """
        INSERT INTO users (name, email, password_hash)
        VALUES (%s, %s, %s)
        """
        cursor.execute(query, (name, email, password_hash))
        db.commit()
        return True, None
    except MySQLError as exc:
        if getattr(exc, "errno", None) == 1062:
            return False, "An account with this email already exists."
        return False, "Unable to create account right now. Please try again."
    finally:
        cursor.close()
        db.close()


# LOGIN VERIFY
def verify_user(email, password):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    query = "SELECT * FROM users WHERE email=%s AND is_active=1"
    cursor.execute(query, (email,))
    user = cursor.fetchone()

    cursor.close()
    db.close()

    if not user:
        return None

    # compare hashed password
    if bcrypt.verify(password, user["password_hash"]):
        return user

    return None


def reset_user_password(email, new_password):
    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        existing = cursor.fetchone()
        if not existing:
            return False, "No account found with this email."

        hashed_password = bcrypt.hash(new_password)
        cursor.execute(
            "UPDATE users SET password_hash=%s WHERE email=%s",
            (hashed_password, email),
        )
        db.commit()
        return True, None
    except MySQLError:
        return False, "Unable to reset password right now. Please try again."
    finally:
        cursor.close()
        db.close()


def user_exists(email):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()
