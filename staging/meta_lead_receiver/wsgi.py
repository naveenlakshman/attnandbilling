"""WSGI entry point for a future isolated staging service."""
from .receiver import create_app, settings_from_env

app = create_app(settings_from_env())
