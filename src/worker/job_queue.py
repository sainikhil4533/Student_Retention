from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime

from dotenv import load_dotenv

from src.alerts.alert_dispatcher import dispatch_alert_email
from src.alerts.guardian_alert_dispatcher import dispatch_guardian_alert
from src.alerts.student_warning_dispatcher import dispatch_student_warning_email
from src.db.database import SessionLocal
from src.db.repository import EventRepository


load_dotenv()

JOB_QUEUE_POLL_SECONDS = float(os.getenv("JOB_QUEUE_POLL_SECONDS", "2"))
ENABLE_BACKGROUND_JOB_WORKER = (
    os.getenv("ENABLE_BACKGROUND_JOB_WORKER", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)

JOB_TYPE_STUDENT_WARNING_EMAIL = "student_warning_email"
JOB_TYPE_FACULTY_ALERT_EMAIL = "faculty_alert_email"
JOB_TYPE_GUARDIAN_ALERT_DELIVERY = "guardian_alert_delivery"


def enqueue_student_warning_email_job(
    *,
    warning_event_id: int,
    student_id: int,
    prediction_history_id: int,
    warning_type: str,
    recipient: str,
) -> int:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        job = repository.enqueue_background_job(
            job_type=JOB_TYPE_STUDENT_WARNING_EMAIL,
            dedupe_key=f"{JOB_TYPE_STUDENT_WARNING_EMAIL}:{warning_event_id}",
            payload={
                "warning_event_id": warning_event_id,
                "student_id": student_id,
                "prediction_history_id": prediction_history_id,
                "warning_type": warning_type,
                "recipient": recipient,
            },
        )
        return int(job.id)
    finally:
        db.close()


def enqueue_faculty_alert_email_job(
    *,
    alert_event_id: int,
    student_id: int,
    prediction_history_id: int,
    alert_type: str,
) -> int:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        job = repository.enqueue_background_job(
            job_type=JOB_TYPE_FACULTY_ALERT_EMAIL,
            dedupe_key=f"{JOB_TYPE_FACULTY_ALERT_EMAIL}:{alert_event_id}",
            payload={
                "alert_event_id": alert_event_id,
                "student_id": student_id,
                "prediction_history_id": prediction_history_id,
                "alert_type": alert_type,
            },
        )
        return int(job.id)
    finally:
        db.close()


def enqueue_guardian_alert_delivery_job(
    *,
    guardian_alert_event_id: int,
) -> int:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        job = repository.enqueue_background_job(
            job_type=JOB_TYPE_GUARDIAN_ALERT_DELIVERY,
            dedupe_key=f"{JOB_TYPE_GUARDIAN_ALERT_DELIVERY}:{guardian_alert_event_id}",
            payload={
                "guardian_alert_event_id": guardian_alert_event_id,
            },
        )
        return int(job.id)
    finally:
        db.close()


def run_background_job_pass() -> dict[str, int]:
    db = SessionLocal()
    processed = 0
    try:
        repository = EventRepository(db)
        job = repository.claim_next_background_job(reference_time=datetime.now(UTC))
        if job is None:
            return {"processed_count": 0}

        payload = job.payload or {}
        try:
            if job.job_type == JOB_TYPE_STUDENT_WARNING_EMAIL:
                dispatch_student_warning_email(
                    warning_event_id=int(payload["warning_event_id"]),
                    student_id=int(payload["student_id"]),
                    prediction_history_id=int(payload["prediction_history_id"]),
                    warning_type=str(payload["warning_type"]),
                    recipient=str(payload["recipient"]),
                )
            elif job.job_type == JOB_TYPE_FACULTY_ALERT_EMAIL:
                dispatch_alert_email(
                    alert_event_id=int(payload["alert_event_id"]),
                    student_id=int(payload["student_id"]),
                    prediction_history_id=int(payload["prediction_history_id"]),
                    alert_type=str(payload["alert_type"]),
                )
            elif job.job_type == JOB_TYPE_GUARDIAN_ALERT_DELIVERY:
                dispatch_guardian_alert(
                    guardian_alert_event_id=int(payload["guardian_alert_event_id"]),
                )
            else:
                raise ValueError(f"Unknown background job type: {job.job_type}")

            repository.update_background_job(
                job.id,
                {
                    "status": "completed",
                    "last_error": None,
                    "completed_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            )
            processed = 1
        except Exception as error:
            repository.update_background_job(
                job.id,
                {
                    "status": "failed",
                    "last_error": str(error),
                    "updated_at": datetime.now(UTC),
                },
            )
            print(f"[worker.queue] job_id={job.id} failed: {error}", flush=True)
        return {"processed_count": processed}
    finally:
        db.close()


async def background_job_worker_loop() -> None:
    print(
        f"[worker.queue] started interval={JOB_QUEUE_POLL_SECONDS}s",
        flush=True,
    )
    try:
        while True:
            try:
                result = await asyncio.to_thread(run_background_job_pass)
                processed = int(result.get("processed_count", 0))
                if processed:
                    print(f"[worker.queue] processed_count={processed}", flush=True)
            except Exception as error:
                print(f"[worker.queue] pass failed: {error}", flush=True)

            await asyncio.sleep(JOB_QUEUE_POLL_SECONDS)
    except asyncio.CancelledError:
        print("[worker.queue] stopped", flush=True)
        raise


async def start_background_job_worker_if_enabled() -> asyncio.Task | None:
    if not ENABLE_BACKGROUND_JOB_WORKER:
        print("[worker.queue] disabled by configuration", flush=True)
        return None
    return asyncio.create_task(background_job_worker_loop())


async def stop_background_job_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
