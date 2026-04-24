from __future__ import annotations

import asyncio

from src.alerts.recovery_monitor import (
    start_recovery_monitor_if_enabled,
    stop_recovery_monitor,
)
from src.reporting.summary_snapshot_monitor import (
    start_summary_snapshot_monitor_if_enabled,
    stop_summary_snapshot_monitor,
)
from src.worker.job_queue import (
    start_background_job_worker_if_enabled,
    stop_background_job_worker,
)


async def _run() -> None:
    # Stagger monitor startup so all 3 don't hit the DB simultaneously.
    # job_queue starts immediately (lightest query), then recovery after 10s,
    # then summary after another 10s. This prevents the connection burst that
    # causes "DbHandler exited" errors on Supabase Free Tier at boot.
    print("[runner] starting job queue worker...", flush=True)
    queue_task = await start_background_job_worker_if_enabled()

    print("[runner] waiting 10s before starting recovery monitor...", flush=True)
    await asyncio.sleep(10)
    recovery_task = await start_recovery_monitor_if_enabled()

    print("[runner] waiting 10s before starting summary monitor...", flush=True)
    await asyncio.sleep(10)
    summary_task = await start_summary_snapshot_monitor_if_enabled()

    try:
        await asyncio.Event().wait()
    finally:
        await stop_background_job_worker(queue_task)
        await stop_recovery_monitor(recovery_task)
        await stop_summary_snapshot_monitor(summary_task)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
