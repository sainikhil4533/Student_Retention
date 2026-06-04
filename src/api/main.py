from pathlib import Path
import os
import sys
from threading import Thread

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError, TimeoutError as SQLAlchemyTimeoutError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.routes.reports import router as reports_router
from src.api.routes.ai_assist import router as ai_assist_router
from src.api.routes.admin_imports import router as admin_imports_router
from src.api.routes.alerts import router as alerts_router
from src.api.routes.auth import router as auth_router
from src.api.routes.cases import router as cases_router
from src.api.routes.config import router as config_router
from src.api.routes.copilot import router as copilot_router
from src.api.routes.drivers import router as drivers_router
from src.api.routes.faculty import router as faculty_router
from src.api.routes.guardian_alerts import router as guardian_alerts_router
from src.api.routes.health import router as health_router
from src.api.routes.ingest import router as ingest_router
from src.api.routes.institution import router as institution_router
from src.api.routes.interventions import router as interventions_router
from src.api.routes.operations import router as operations_router
from src.api.routes.predict import router as predict_router
from src.api.routes.profile import router as profile_router
from src.api.routes.recovery import router as recovery_router
from src.api.routes.repeated_risk import router as repeated_risk_router
from src.api.routes.score import router as score_router
from src.api.routes.student import router as student_router
from src.api.routes.timeline import router as timeline_router
from src.api.routes.warnings import router as warnings_router
from src.db.database import Base, engine
app = FastAPI(title="Student Retention Prediction API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Student Retention API is running"}


def _prewarm_dashboard_caches() -> None:
    from src.api.auth import AuthContext
    from src.api.routes.institution import get_institution_risk_overview
    from src.api.routes.reports import get_import_coverage_report
    from src.db.database import db_session_scope

    try:
        auth = AuthContext(role="system", subject="system")
        with db_session_scope() as db:
            get_institution_risk_overview(
                imported_only=False,
                include_academic_pressure=False,
                db=db,
                auth=auth,
            )
        with db_session_scope() as db:
            get_import_coverage_report(imported_only=True, limit=100, db=db, auth=auth)
    except Exception as error:
        print(f"[startup.prewarm] skipped: {error}", flush=True)


def _warm_database_connection() -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        print(f"[startup.db] warmup skipped: {error}", flush=True)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    if isinstance(exc, (OperationalError, SQLAlchemyTimeoutError, DBAPIError)):
        pool_status = "unavailable"
        try:
            pool_status = engine.pool.status()
        except Exception:
            pass
        print(
            f"[db.error] {type(exc).__name__} on {request.method} {request.url.path}: "
            f"{exc}; pool={pool_status}",
            flush=True,
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database is temporarily unavailable or busy. "
                    "Please retry in a moment."
                )
            },
        )
    return JSONResponse(status_code=500, content={"detail": "Database operation failed."})


@app.on_event("startup")
def ensure_runtime_tables() -> None:
    auto_create_tables = str(os.getenv("RETENTIONOS_AUTO_CREATE_TABLES", "false")).strip().lower()
    if auto_create_tables in {"1", "true", "yes", "on"}:
        Base.metadata.create_all(bind=engine)
    if str(os.getenv("RETENTIONOS_PREWARM_DB", "true")).strip().lower() not in {"0", "false", "no", "off"}:
        _warm_database_connection()
    # Heavy dashboard prewarm competes with the first real user requests on the
    # small Supabase pooler, so keep it opt-in for local/dev stability.
    prewarm = str(os.getenv("RETENTIONOS_PREWARM_DASHBOARD_CACHE", "false")).strip().lower()
    if prewarm not in {"0", "false", "no", "off"}:
        Thread(target=_prewarm_dashboard_caches, daemon=True).start()


@app.on_event("shutdown")
def close_database_pool() -> None:
    engine.dispose()


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


app.include_router(alerts_router)
app.include_router(ai_assist_router)
app.include_router(admin_imports_router)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(health_router)
app.include_router(config_router)
app.include_router(copilot_router)
app.include_router(drivers_router)
app.include_router(faculty_router)
app.include_router(guardian_alerts_router)
app.include_router(ingest_router)
app.include_router(institution_router)
app.include_router(interventions_router)
app.include_router(operations_router)
app.include_router(profile_router)
app.include_router(predict_router)
app.include_router(recovery_router)
app.include_router(repeated_risk_router)
app.include_router(reports_router)
app.include_router(score_router)
app.include_router(student_router)
app.include_router(timeline_router)
app.include_router(warnings_router)
