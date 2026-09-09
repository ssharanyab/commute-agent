"""
HTTP API package for the Commute Agent.

Thin FastAPI layer over ADK Mobility Orchestrator + adaptive replan.
"""

from src.api.app import create_app, app

__all__ = ["create_app", "app"]
