from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"

def _spawn(command: list[str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=cwd or PROJECT_ROOT)


def _parse_flags(argv: Iterable[str]) -> tuple[bool, bool]:
    with_frontend = False
    with_worker = True
    for arg in argv:
        normalized = str(arg).strip().lower()
        if normalized == "--with-frontend":
            with_frontend = True
        elif normalized == "--no-worker":
            with_worker = False
    return with_frontend, with_worker


def main() -> int:
    with_frontend, with_worker = _parse_flags(sys.argv[1:])
    processes: list[subprocess.Popen] = []

    print("[run_all] starting backend on http://127.0.0.1:8000")
    backend = _spawn([sys.executable, "-m", "uvicorn", "src.api.main:app", "--reload"])
    processes.append(backend)

    if with_worker:
        print("[run_all] starting background worker")
        worker = _spawn([sys.executable, "-m", "src.worker.runner"])
        processes.append(worker)
    else:
        print("[run_all] worker disabled via --no-worker")

    if with_frontend:
        print("[run_all] starting frontend dev server")
        frontend = _spawn(["cmd", "/c", "npm", "run", "dev"], cwd=FRONTEND_ROOT)
        processes.append(frontend)
    else:
        print("[run_all] frontend not started. Use --with-frontend if you want the Vite dev server too.")

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    return code
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
