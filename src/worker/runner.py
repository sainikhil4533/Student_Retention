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
    recovery_task = await start_recovery_monitor_if_enabled()
    summary_task = await start_summary_snapshot_monitor_if_enabled()
    queue_task = await start_background_job_worker_if_enabled()
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
