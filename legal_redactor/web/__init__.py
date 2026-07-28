"""Modular Web UI package for legal-redactor.

Public entrypoint remains ``legal_redactor.web_app:app`` for CLI and tests.
"""
from .app import app, register_routes

__all__ = ["app", "register_routes"]
