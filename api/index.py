"""Vercel entry point for the API (Step F6). Vercel serves the ASGI object named `app` from this file.
Nothing is configured here: settings come from environment variables, exactly as on any other host."""
from app.main import app  # noqa: F401
