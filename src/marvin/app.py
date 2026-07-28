"""
This module serves as the main entry point for the Marvin FastAPI application.

It initializes the FastAPI application instance, configures middleware (CORS, GZip),
sets up lifespan events for application startup and shutdown (including database
initialization and scheduler startup), registers API routes, and provides a `main`
function to run the application using Uvicorn, primarily for development purposes.
"""

import copy  # Deep-copy Uvicorn's logging config before customizing it
import logging  # Access-log filtering (silence health probes)
from collections.abc import AsyncGenerator  # For async generator type hint
from contextlib import asynccontextmanager  # For creating async context managers (lifespan)

import uvicorn  # ASGI server for running FastAPI
from fastapi import FastAPI  # The main FastAPI class
from fastapi.middleware.cors import CORSMiddleware  # Middleware for CORS
from fastapi.middleware.gzip import GZipMiddleware  # Middleware for GZip compression
from fastapi.staticfiles import StaticFiles  # Static file serving

# Marvin core components
from marvin.core.config import get_app_settings  # Access application settings
from marvin.core.root_logger import get_logger  # Application logger
from marvin.core.settings.static import APP_VERSION  # Static application version
from marvin.routes import router as main_api_router  # Main API router combining all app routes
from marvin.routes.handlers import (  # Registers custom exception handlers
    register_core_exception_handlers,
    register_debug_handler,
)

# Scheduler components
from marvin.services.scheduler import SchedulerRegistry, SchedulerService
from marvin.services.scheduler import tasks as scheduler_tasks

# Initialize global settings and logger instances
settings = get_app_settings()
logger = get_logger()

# Application description for OpenAPI documentation
# Uses f-string to embed the current application version.
description = f"""
Marvin API - Your central hub for managing things.
Version: **{APP_VERSION}**
"""


@asynccontextmanager
async def lifespan_fn(_app: FastAPI) -> AsyncGenerator[None, None]:  # Renamed app to _app
    """
    Asynchronous context manager for FastAPI application lifespan events.

    This function handles tasks that need to occur at application startup
    (before `yield`) and shutdown (after `yield`).

    Startup tasks include:
    - Logging system startup.
    - Initializing the database (running migrations, creating default data via `init_db.main()`).
    - Starting the scheduler service (`start_scheduler()`).
    - Logging application settings (excluding sensitive information).

    Shutdown tasks include:
    - Logging system shutdown.

    Args:
        _app (FastAPI): The FastAPI application instance (passed by FastAPI, often unused in the function body).

    Yields:
        None: Control back to FastAPI after startup tasks are complete.
    """
    # --- Startup ---
    logger.info("------ SYSTEM STARTUP INITIATED ------")

    logger.info("Starting: Database initialization...")
    import marvin.db.init_db as init_db  # Local import to avoid premature DB calls if app is imported elsewhere

    try:
        init_db.main()  # Run database migrations and initial data seeding
        logger.info("Completed: Database initialization.")
    except Exception as e:
        logger.exception(f"Database initialization failed: {e}")
        # Depending on severity, might want to raise or exit here.

    logger.info("Starting: Email template seeder...")
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.email.system_templates import seed_system_templates

        with session_context() as session:
            count = seed_system_templates(session)
            if count:
                logger.info(f"Email template seeder: created {count} system template(s).")
    except Exception as e:
        logger.exception(f"Email template seeder failed: {e}")

    logger.info("Starting: Scheduled task seeder...")
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.scheduled_tasks.system_tasks import seed_system_scheduled_tasks

        with session_context() as session:
            count = seed_system_scheduled_tasks(session)
            if count:
                logger.info(f"Scheduled task seeder: created {count} system task(s).")
    except Exception as e:
        logger.exception(f"Scheduled task seeder failed: {e}")

    logger.info("Starting: System collections seeder...")
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.collections.system_collections import seed_all_workspaces

        with session_context() as session:
            count = seed_all_workspaces(session)
            if count:
                logger.info(f"System collections seeder: created {count} collection(s).")
    except Exception as e:
        logger.exception(f"System collections seeder failed: {e}")

    if settings.SCHEDULER_ENABLED:
        logger.info("Starting: Scheduler service...")
        try:
            await start_scheduler()  # Register and start scheduled tasks
            logger.info("Completed: Scheduler service started.")
        except Exception as e:
            logger.exception(f"Scheduler service failed to start: {e}")
    else:
        logger.info("Scheduler service disabled by SCHEDULER_ENABLED=False.")

    logger.info("------ APPLICATION SETTINGS (Non-Sensitive) ------")
    # Log application settings, excluding potentially sensitive fields
    # Pydantic v2 uses model_dump_json
    loggable_settings = settings.model_dump_json(
        indent=2,
        exclude={"theme", "SECRET", "ENV_SECRETS"},  # Exclude sensitive or verbose fields
    )
    logger.info(loggable_settings)
    logger.info("------ SYSTEM STARTUP COMPLETE ------")

    yield  # Application runs after this point

    # --- Shutdown ---
    logger.info("------ SYSTEM SHUTDOWN INITIATED ------")

    if settings.SCHEDULER_ENABLED:
        # Drop the scheduler lease so a surviving replica picks the work up on its next tick
        # instead of waiting out the TTL. Best-effort: a rolling restart must not hang on it.
        try:
            from marvin.db.db_setup import session_context
            from marvin.services.scheduler.leader import release as release_scheduler_lease

            with session_context() as session:
                release_scheduler_lease(session)
        except Exception as e:
            logger.warning(f"Could not release the scheduler lease on shutdown: {e}")

    logger.info("------ SYSTEM SHUTDOWN COMPLETE ------")


# Initialize the FastAPI application instance
app = FastAPI(
    title="Marvin API",  # Title for OpenAPI documentation
    description=description,  # Description from above
    version=APP_VERSION,  # Application version
    docs_url=settings.DOCS_URL,  # URL for Swagger UI (None if disabled in settings)
    redoc_url=settings.REDOC_URL,  # URL for ReDoc (None if disabled in settings)
    lifespan=lifespan_fn,  # Register the lifespan context manager
)

# Add GZip middleware to compress responses for supported clients
app.add_middleware(GZipMiddleware, minimum_size=1000)  # Compress responses larger than 1KB

# Configure CORS (Cross-Origin Resource Sharing) middleware for non-production environments
if not settings.PRODUCTION:
    # In development, allow all localhost origins to support flexible frontend ports
    # This regex pattern matches http://localhost:* and http://127.0.0.1:*
    logger.info("CORS enabled for development. Allowing all localhost origins.")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",  # Match any localhost port
        allow_credentials=True,  # Allow cookies to be included in cross-origin requests
        allow_methods=["*"],  # Allow all standard HTTP methods
        allow_headers=["*"],  # Allow all headers
    )
else:
    logger.info("CORS middleware not enabled in production environment (or using different production CORS config).")

# Add request logging middleware for development
if not settings.PRODUCTION:
    import time

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class RequestLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start_time = time.time()

            # Log incoming request
            logger.info(f"➡️  {request.method} {request.url.path}")
            if request.query_params:
                logger.debug(f"   Query: {dict(request.query_params)}")

            # Process request
            response = await call_next(request)

            # Log response
            duration = (time.time() - start_time) * 1000  # Convert to milliseconds
            status_emoji = "✅" if response.status_code < 400 else "❌"
            logger.info(f"{status_emoji} {request.method} {request.url.path} → {response.status_code} ({duration:.0f}ms)")

            return response

    app.add_middleware(RequestLoggingMiddleware)
    logger.info("Request logging middleware enabled for development.")


async def start_scheduler() -> None:
    """
    Registers scheduled tasks with the `SchedulerRegistry` and starts the `SchedulerService`.

    This function defines which tasks run at daily, minutely, and hourly intervals.
    Commented-out tasks indicate potential future or optional scheduled jobs.
    """
    logger.info("Registering scheduled tasks...")
    # Register daily tasks
    SchedulerRegistry.register_daily(
        # scheduler_tasks.purge_expired_tokens,
        # scheduler_tasks.purge_group_registration,
        # scheduler_tasks.purge_password_reset_tokens,
        # scheduler_tasks.purge_group_data_exports,
        # scheduler_tasks.delete_old_checked_list_items,
    )

    # Register minutely tasks (ping, webhooks, and scheduled tasks checker)
    SchedulerRegistry.register_minutely(
        scheduler_tasks.ping,
        scheduler_tasks.post_group_webhooks,
        scheduler_tasks.check_scheduled_tasks,
    )

    # Register hourly tasks
    SchedulerRegistry.register_hourly(
        # scheduler_tasks.locked_user_reset,
    )

    # Print all registered jobs to the debug log for verification
    SchedulerRegistry.print_jobs()

    # Start the scheduler service (which will pick up registered tasks)
    await SchedulerService.start()


# Register custom debug/error handlers for the application
# This is conditional based on settings in register_debug_handler
register_debug_handler(app)

# Register global core exception handlers (always active)
register_core_exception_handlers(app)


def include_api_routers() -> None:  # Renamed from api_routers for clarity
    """
    Includes the main API router into the FastAPI application.

    This function modularizes router inclusion. All application routes
    are aggregated under `main_api_router` (imported from `marvin.routes`).
    """
    app.include_router(main_api_router)  # Include all routes defined in marvin.routes

    # Root-level health probes (/healthz, /livez, /health, /readyz) — mounted outside the /api
    # prefix so infra doesn't need to know where the API lives.
    from marvin.routes.health_root import router as health_router

    app.include_router(health_router)
    logger.info("API routers included.")


# Include all API routes from marvin.routes package
include_api_routers()


# Mount static files for local storage provider
if settings.STORAGE_PROVIDER == "local":
    from marvin.core.config import get_app_dirs

    storage_root = settings.STORAGE_LOCAL_ROOT or get_app_dirs().ASSETS_DIR
    storage_root.mkdir(parents=True, exist_ok=True)

    app.mount(
        settings.STORAGE_LOCAL_PUBLIC_URL,
        StaticFiles(directory=str(storage_root)),
        name="assets",
    )
    logger.info(f"Static file serving enabled for local storage at {storage_root} (public URL: {settings.STORAGE_LOCAL_PUBLIC_URL})")


class HealthCheckAccessFilter(logging.Filter):
    """Drop Uvicorn access-log lines for infrastructure probes.

    The k8s liveness/readiness probes (/healthz, /readyz) and the frontend's per-probe login-info
    poll hit the API every few seconds; logging each one buries real traffic. Uvicorn's access
    record carries the request path in args[2] (msg '%s - "%s %s HTTP/%s" %d').
    """

    _NOISY_PATHS = frozenset({"/healthz", "/readyz", "/livez", "/api/app/about/login-info"})

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        path = args[2] if isinstance(args, tuple) and len(args) >= 3 else None
        if isinstance(path, str) and path.split("?", 1)[0] in self._NOISY_PATHS:
            return False
        return True


def _uvicorn_log_config() -> dict:
    """Uvicorn's default logging config with a filter that silences health-probe access lines."""
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    config.setdefault("filters", {})["health_probes"] = {"()": f"{__name__}.HealthCheckAccessFilter"}
    config["handlers"]["access"].setdefault("filters", []).append("health_probes")
    return config


def main() -> None:
    """
    Main function to run the Marvin FastAPI application using Uvicorn.

    This function is intended for development and local execution. It configures
    Uvicorn with settings for host, port, auto-reloading, logging, and workers.
    For production deployments, a more robust ASGI server setup (e.g., Uvicorn
    managed by Gunicorn or another process manager) is typically used.
    """
    logger.info(f"Starting Uvicorn server for Marvin app (Version: {APP_VERSION})...")
    # Configure and run Uvicorn server
    uvicorn.run(
        "marvin.app:app",  # Path to the FastAPI app instance (module:variable)
        host="0.0.0.0",  # Listen on all available network interfaces
        port=settings.API_PORT,  # Port from application settings
        reload=not settings.PRODUCTION,  # Enable auto-reloading in non-production environments
        reload_dirs=["."] if not settings.PRODUCTION else None,  # Directories to watch for changes
        reload_delay=2 if not settings.PRODUCTION else None,  # Delay before reloading
        log_level="info",  # Uvicorn's own log level
        use_colors=True,  # Enable colored logging output
        log_config=_uvicorn_log_config(),  # Uvicorn defaults + a filter that drops health-probe lines

        workers=1,  # Number of worker processes (typically 1 for dev, more for prod)
        forwarded_allow_ips="*",  # Trust X-Forwarded-For headers from any IP (specific IPs better for prod)
    )


__all__ = ["main"]

if __name__ == "__main__":
    # This block executes when the script is run directly (e.g., `python marvin/app.py`)
    main()
