"""Registers every module's HTTP router on the app (integrator; interfaces.md "DI composition").

Modules add their ``presentation/http/router.py`` here as they land; none has one yet.
"""

from __future__ import annotations

from fastapi import FastAPI


def include_routers(app: FastAPI) -> None:
    """Include the module routers; ``main.create_app`` calls this once."""
