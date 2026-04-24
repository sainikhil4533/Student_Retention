from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.db.database import SessionLocal, run_with_retry
from src.db.repository import EventRepository
from src.reporting.faculty_summary_snapshot_service import (
    create_faculty_summary_snapshot,
    deliver_faculty_summary_snapshot_email,
)


load_dotenv()

SUMMARY_SNAPSHOT_CHECK_SECONDS = int(
    os.getenv("SUMMARY_SNAPSHOT_CHECK_SECONDS", "3600")
)
ENABLE_SUMMARY_SNAPSHOT_MONITOR = (
    os.getenv("ENABLE_SUMMARY_SNAPSHOT_MONITOR", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
ENABLE_FACULTY_DAILY_SUMMARY_EMAIL = (
    os.getenv("ENABLE_FACULTY_DAILY_SUMMARY_EMAIL", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
SUMMARY_SNAPSHOT_HOUR_IST = int(os.getenv("SUMMARY_SNAPSHOT_HOUR_IST", "8"))
IST = ZoneInfo("Asia/Kolkata")


def _do_summary_pass(db) -> dict[str, int]:
    """Inner function: runs one summary snapshot pass on a given DB session."""
    now_ist = datetime.now(IST)
    if now_ist.hour < SUMMARY_SNAPSHOT_HOUR_IST:
        return {"snapshot_count": 0, "email_count": 0}

    repository = EventRepository(db)
    latest_daily = repository.get_latest_faculty_summary_snapshot(snapshot_type="daily")
    if latest_daily is not None and latest_daily.generated_at is not None:
        latest_daily_ist = latest_daily.generated_at.astimezone(IST)
        if latest_daily_ist.date() == now_ist.date():
            return {"snapshot_count": 0, "email_count": 0}

    snapshot = create_faculty_summary_snapshot(db, snapshot_type="daily")
    email_count = 0
    if ENABLE_FACULTY_DAILY_SUMMARY_EMAIL:
        delivered = deliver_faculty_summary_snapshot_email(db, snapshot_id=snapshot.id)
        if delivered.email_delivery_status in {"sent", "skipped", "failed"}:
            email_count = 1
    print(
        "[summary.monitor] created daily faculty summary snapshot",
        flush=True,
    )
    return {"snapshot_count": 1, "email_count": email_count}


def run_summary_snapshot_pass() -> dict[str, int]:
    return run_with_retry(_do_summary_pass, max_retries=3, label="summary.monitor")


async def summary_snapshot_monitor_loop() -> None:
    print(
        f"[summary.monitor] started interval={SUMMARY_SNAPSHOT_CHECK_SECONDS}s",
        flush=True,
    )
    # Initial sleep: avoids DB burst at startup alongside job_queue and recovery monitors
    await asyncio.sleep(5)
    try:
        while True:
            try:
                result = await asyncio.to_thread(run_summary_snapshot_pass)
                created = int(result.get("snapshot_count", 0))
                emailed = int(result.get("email_count", 0))
                if created:
                    print(
                        f"[summary.monitor] snapshot_count={created}",
                        flush=True,
                    )
                if emailed:
                    print(
                        f"[summary.monitor] summary_email_count={emailed}",
                        flush=True,
                    )
            except Exception as error:
                print(f"[summary.monitor] pass failed: {error}", flush=True)

            await asyncio.sleep(SUMMARY_SNAPSHOT_CHECK_SECONDS)
    except asyncio.CancelledError:
        print("[summary.monitor] stopped", flush=True)
        raise


async def start_summary_snapshot_monitor_if_enabled() -> asyncio.Task | None:
    if not ENABLE_SUMMARY_SNAPSHOT_MONITOR:
        print("[summary.monitor] disabled by configuration", flush=True)
        return None
    return asyncio.create_task(summary_snapshot_monitor_loop())


async def stop_summary_snapshot_monitor(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
