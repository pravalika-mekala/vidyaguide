import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

from app.settings import get_settings

_pool: MySQLConnectionPool | None = None


def init_db_pool() -> None:
    global _pool
    if _pool is not None:
        return

    settings = get_settings()
    _pool = MySQLConnectionPool(
        pool_name=settings.db_pool_name,
        pool_size=settings.db_pool_size,
        host=settings.db_host,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        port=settings.db_port,
        connection_timeout=5,
    )


def get_db():
    init_db_pool()
    return _pool.get_connection()
