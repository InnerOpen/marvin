"""Workspace Secrets — pluggable secret backend system."""

from .base import SecretBackend
from .factory import get_secret_backend

__all__ = ["get_secret_backend", "SecretBackend"]
