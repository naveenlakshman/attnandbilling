"""Regression checks for public website tenant isolation.

This test deliberately uses a small fake connection so it can run in Cloud
Build without access to either staging or production data.
"""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.website import website_bp
from modules.website import routes


class FakeCursor:
    def __init__(self, course_exists=False):
        self.course_exists = course_exists
        self.last_sql = ""
        self.last_args = ()

    def execute(self, sql, args=()):
        self.last_sql = " ".join(sql.split())
        self.last_args = tuple(args)
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return {"id": 701} if self.course_exists else None


class FakeConnection:
    def __init__(self, course_exists=False):
        self.cursor_instance = FakeCursor(course_exists=course_exists)

    def cursor(self):
        return self.cursor_instance

    def execute(self, sql, args=()):
        return self.cursor_instance.execute(sql, args)

    def close(self):
        pass


def main():
    app = Flask(__name__, template_folder="../templates")
    app.secret_key = "public-website-isolation-regression"
    app.register_blueprint(website_bp)

    connections = []

    def fake_get_conn():
        connection = FakeConnection()
        connections.append(connection)
        return connection

    original_get_conn = routes.get_conn
    original_get_institute = routes.get_current_institute_id
    original_render_template = routes.render_template
    try:
        routes.get_conn = fake_get_conn
        routes.get_current_institute_id = lambda default=None: 7
        routes.render_template = lambda *args, **kwargs: "tenant home"

        response = app.test_client().get("/", headers={"Host": "harsha.example.test"})
        assert response.status_code == 200
        home_query = connections[-1].cursor_instance
        assert "WHERE institute_id = ?" in home_query.last_sql
        assert home_query.last_args == (7,)

        response = app.test_client().get(
            "/courses/ccom", headers={"Host": "harsha.example.test"}
        )
        assert response.status_code == 404
        detail_query = connections[-1].cursor_instance
        assert "WHERE institute_id = ? AND course_slug = ?" in detail_query.last_sql
        assert detail_query.last_args == (7, "ccom")
    finally:
        routes.get_conn = original_get_conn
        routes.get_current_institute_id = original_get_institute
        routes.render_template = original_render_template

    print("Public website tenant-isolation regression checks passed.")


if __name__ == "__main__":
    main()
