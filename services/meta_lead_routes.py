"""Least-privilege access to configurable Meta lead routing."""
from __future__ import annotations

import os

import pymysql
from pymysql.cursors import DictCursor


def connect(environ=None):
    env = os.environ if environ is None else environ
    password = env.get("META_ROUTING_DB_PASSWORD", "")
    if not password:
        raise RuntimeError("Meta routing database credentials are not configured.")
    kwargs = {
        "user": env.get("META_ROUTING_DB_USER", "meta_leads_admin"),
        "password": password,
        "database": env.get("META_ROUTING_DB_NAME", "meta_leads_inbox"),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 20,
        "write_timeout": 20,
    }
    socket = env.get("META_ROUTING_DB_UNIX_SOCKET")
    if socket:
        kwargs["unix_socket"] = socket
    else:
        kwargs["host"] = env.get("META_ROUTING_DB_HOST", "127.0.0.1")
        kwargs["port"] = int(env.get("META_ROUTING_DB_PORT", "3306"))
    return pymysql.connect(**kwargs)


def list_routes(institute_id: int):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id,institute_id,page_id,form_id,course_id,batch_id,branch_id,
            counsellor_user_id,is_active,created_by_user_id,updated_by_user_id,created_at,updated_at
            FROM routes WHERE institute_id=%s ORDER BY is_active DESC,page_id,form_id""", (institute_id,))
        routes = cur.fetchall()
        cur.execute("""SELECT page_id,form_id,COUNT(*) AS pending_review
            FROM notifications WHERE state='REVIEW' GROUP BY page_id,form_id
            ORDER BY pending_review DESC,page_id,form_id LIMIT 100""")
        reviews = cur.fetchall()
    return routes, reviews


def save_route(*, institute_id: int, page_id: str, form_id: str, course_id: int,
               batch_id: int, branch_id: int, counsellor_user_id: int, is_active: bool,
               actor_user_id: int):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO routes
            (institute_id,page_id,form_id,course_id,batch_id,branch_id,counsellor_user_id,
             is_active,created_by_user_id,updated_by_user_id,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
            ON DUPLICATE KEY UPDATE course_id=VALUES(course_id),batch_id=VALUES(batch_id),
             branch_id=VALUES(branch_id),counsellor_user_id=VALUES(counsellor_user_id),
             is_active=VALUES(is_active),updated_by_user_id=VALUES(updated_by_user_id),
             updated_at=UTC_TIMESTAMP(6)""",
            (institute_id, page_id, form_id, course_id, batch_id, branch_id,
             counsellor_user_id, int(is_active), actor_user_id, actor_user_id))
        cur.execute("SELECT id FROM routes WHERE institute_id=%s AND page_id=%s AND form_id=%s",
                    (institute_id, page_id, form_id))
        route_id = int(cur.fetchone()["id"])
        conn.commit()
    return route_id

