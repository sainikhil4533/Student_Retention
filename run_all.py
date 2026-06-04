from __future__ import annotations

import signal
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"

WORKER_MAX_RESTARTS = 5        # restart the worker up to 5 times before giving up
WORKER_RESTART_DELAY = 10      # seconds to wait before restarting


def _spawn(command: list[str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=cwd or PROJECT_ROOT)


def _spawn_worker() -> subprocess.Popen:
    env = os.environ.copy()
    env["RETENTIONOS_PROCESS_ROLE"] = "worker"
    return subprocess.Popen(
        [sys.executable, "-m", "src.worker.runner"],
        cwd=PROJECT_ROOT,
        env=env,
    )


def _parse_flags(argv: Iterable[str]) -> tuple[bool, bool, bool]:
    with_frontend = False
    with_worker = False
    backend_reload = False
    for arg in argv:
        normalized = str(arg).strip().lower()
        if normalized == "--with-frontend":
            with_frontend = True
        elif normalized == "--with-worker":
            with_worker = True
        elif normalized == "--no-worker":
            with_worker = False
        elif normalized == "--reload":
            backend_reload = True
    return with_frontend, with_worker, backend_reload


def main() -> int:
    with_frontend, with_worker, backend_reload = _parse_flags(sys.argv[1:])

    print("[run_all] starting backend on http://127.0.0.1:8000")
    backend_command = [
        sys.executable, "-m", "uvicorn", "src.api.main:app",
        "--timeout-keep-alive", "30",
    ]
    if backend_reload:
        backend_command.append("--reload")
    backend = _spawn(backend_command)
    processes: list[subprocess.Popen] = [backend]

    worker: subprocess.Popen | None = None
    worker_restarts = 0

    if with_worker:
        print("[run_all] waiting 5 seconds before starting background worker...")
        time.sleep(5)
        print("[run_all] starting background worker")
        worker = _spawn_worker()
    else:
        print("[run_all] worker not started. Use --with-worker only when background delivery is needed.")

    if with_frontend:
        print("[run_all] starting frontend dev server")
        frontend = _spawn(["cmd", "/c", "npm", "run", "dev"], cwd=FRONTEND_ROOT)
        processes.append(frontend)
    else:
        print("[run_all] frontend not started. Use --with-frontend if you want the Vite dev server too.")

    try:
        while True:
            # Check if backend (critical) has exited — if so, stop everything
            if backend.poll() is not None:
                print(f"[run_all] backend exited with code {backend.returncode}, shutting down.")
                return backend.returncode or 1

            # Check if worker has crashed — restart it (non-critical)
            if worker is not None and worker.poll() is not None:
                if worker_restarts < WORKER_MAX_RESTARTS:
                    worker_restarts += 1
                    print(
                        f"[run_all] worker exited (code {worker.returncode}). "
                        f"Restart {worker_restarts}/{WORKER_MAX_RESTARTS} in {WORKER_RESTART_DELAY}s..."
                    )
                    time.sleep(WORKER_RESTART_DELAY)
                    worker = _spawn_worker()
                else:
                    print(
                        f"[run_all] worker exceeded max restarts ({WORKER_MAX_RESTARTS}). "
                        "Running without background worker. Core app continues."
                    )
                    worker = None  # stop trying — core app still works

            time.sleep(2)

    except KeyboardInterrupt:
        return 0
    finally:
        # Shut down all active processes
        all_procs = [p for p in [*processes, worker] if p is not None]
        for process in all_procs:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
        for process in all_procs:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
