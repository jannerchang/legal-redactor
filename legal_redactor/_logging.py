"""Centralized logging configuration for legal-redactor.

Provides a named logger so that core modules (llm, io, crypto, pipeline, etc.)
can emit diagnostic messages without scattering ``print(..., file=sys.stderr)``
calls across the codebase.  CLI entry-points that need user-facing stdout output
may continue using ``print()`` directly; this module is for internal diagnostics.
"""

from __future__ import annotations

import logging

_LOGGER_NAME = "legal_redactor"

_logger: logging.Logger | None = None


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the shared ``legal_redactor`` logger (or a child of it).

    The first call configures a ``StreamHandler`` on *stderr* with a concise
    format that preserves the previous ``[legal-redactor]`` prefix style for
    backward compatibility.
    """
    global _logger
    if _logger is None:
        _logger = logging.getLogger(_LOGGER_NAME)
        if not _logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter("[legal-redactor] %(message)s")
            handler.setFormatter(formatter)
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
    if name and name != _LOGGER_NAME:
        return _logger.getChild(name)
    return _logger


def set_level(level: int | str) -> None:
    """Adjust the logging level at runtime (e.g. ``logging.DEBUG``)."""
    get_logger().setLevel(level)
