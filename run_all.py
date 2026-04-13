from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def _spawn(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=PROJECT_ROOT)


def main() -> int:
    backend = _spawn([sys.executable, "-m", "uvicorn", "src.api.main:app", "--reload"])
    worker = _spawn([sys.executable, "-m", "src.worker.runner"])
    processes = [backend, worker]

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
