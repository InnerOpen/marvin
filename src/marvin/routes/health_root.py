"""Root-level health endpoints for infrastructure probes.

These live at the application root — not under the ``/api`` prefix — so orchestrators, load
balancers and container HEALTHCHECKs can probe them without knowing where the API is mounted. The
names follow the cloud-native convention:

    /healthz, /livez  — liveness: the process is up and serving. Cheap, no dependencies.
    /health           — liveness alias for tooling that reaches for the un-suffixed name.
    /readyz           — readiness: dependencies (the database) are reachable, so the instance can
                        actually handle traffic.

The legacy ``/api/app/health`` endpoint stays in place for back-compat (see routes/app/health.py).
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


class HealthStatus(BaseModel):
    status: str = "ok"


@router.get("/healthz", summary="Liveness probe", response_model=HealthStatus)
@router.get("/livez", summary="Liveness probe (alias)", response_model=HealthStatus)
@router.get("/health", summary="Liveness probe (alias)", response_model=HealthStatus)
def liveness() -> HealthStatus:
    """Return 200 while the process is up. No dependencies are touched."""
    return HealthStatus(status="ok")


@router.get("/readyz", summary="Readiness probe", response_model=HealthStatus)
def readiness(response: Response) -> HealthStatus:
    """Return 200 only when the database answers, 503 otherwise.

    Readiness gates traffic, so an instance that can't reach its database must report not-ready
    even though the process itself is alive.
    """
    from sqlalchemy import text

    from marvin.db.db_setup import session_context

    try:
        with session_context() as session:
            session.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — any failure means not ready
        logger.warning(f"readiness check failed: {e}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable")

    return HealthStatus(status="ok")
