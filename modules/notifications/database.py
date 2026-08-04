from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from config import Config, DB_PATH
from .models import Base

_engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def _build_engine():
    if Config.DB_TYPE != "mysql":
        return create_engine(f"sqlite:///{DB_PATH}", pool_pre_ping=True)

    if Config.DB_CONNECTION_MODE == "cloud-sql-connector":
        from db import _get_cloud_sql_connection
        return create_engine(
            "mysql+pymysql://",
            creator=_get_cloud_sql_connection,
            pool_pre_ping=True,
            poolclass=NullPool,
        )

    connection_args = {}
    host = Config.MYSQL_HOST
    port = Config.MYSQL_PORT
    if Config.MYSQL_UNIX_SOCKET:
        connection_args["unix_socket"] = Config.MYSQL_UNIX_SOCKET
        host = None
        port = None
    url = URL.create(
        "mysql+pymysql",
        username=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        host=host,
        port=port,
        database=Config.MYSQL_DB,
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, connect_args=connection_args, pool_pre_ping=True, pool_recycle=1800)


def init_notification_database():
    global _engine
    if _engine is None:
        _engine = _build_engine()
        SessionLocal.configure(bind=_engine)
        if Config.DB_TYPE == "mysql":
            # Gunicorn imports the app in multiple workers. Serialize the initial
            # DDL inspection/creation so workers cannot race on DESCRIBE/CREATE.
            with _engine.connect() as connection:
                acquired = connection.execute(
                    text("SELECT GET_LOCK('global_it_erp_notifications_schema_v2', 30)")
                ).scalar()
                if acquired != 1:
                    raise RuntimeError("Timed out waiting for notification schema lock")
                try:
                    Base.metadata.create_all(connection)
                    connection.commit()
                finally:
                    connection.execute(
                        text("SELECT RELEASE_LOCK('global_it_erp_notifications_schema_v2')")
                    )
        else:
            Base.metadata.create_all(_engine)
    return _engine


def notification_session():
    init_notification_database()
    return SessionLocal()
