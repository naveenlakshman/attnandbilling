from functools import wraps
from flask import session, flash, redirect, url_for

def login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("core.login"))
        return route_function(*args, **kwargs)
    return wrapper