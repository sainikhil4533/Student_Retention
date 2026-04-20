from __future__ import annotations

import json
import time
from pathlib import Path

from tests.chatbot_test_runner import (
    InProcessChatbotClient,
    SessionLocal,
    EventRepository,
    _build_dataset_context,
)


PROMPTS = [
    "who needs attention",
    "which students are struggling",
    "any critical cases",
    "who should I focus on",
    "which students are not doing well",
    "who is in trouble",
]

LOG_PATH = Path("tests/artifacts/tmp_counsellor_natural_live_trace.log")


def _log(payload: dict[str, object]) -> None:
    line = json.dumps(payload, ensure_ascii=True)
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    _log({"event": "trace_boot"})
    with SessionLocal() as db:
        _log({"event": "db_session_open"})
        repository = EventRepository(db)
        _log({"event": "repository_ready"})
        context = _build_dataset_context(repository)
        _log({"event": "context_ready", "counsellor_subject": context.counsellor_auth.subject})
        client = InProcessChatbotClient(
            repository,
            context.counsellor_auth,
            deterministic_planner_only=True,
        )
        _log({"event": "client_ready", "session_id": client.session_id})
        results: list[dict[str, object]] = []
        for index, prompt in enumerate(PROMPTS, start=1):
            start = time.perf_counter()
            _log({"event": "turn_start", "turn": index, "prompt": prompt})
            payload = client.send(prompt)
            elapsed = round(time.perf_counter() - start, 3)
            result = {
                "turn": index,
                "prompt": prompt,
                "elapsed_seconds": elapsed,
                "response_type": payload.get("response_type"),
                "last_topic": payload.get("last_topic"),
                "last_intent": payload.get("last_intent"),
                "answer": payload.get("answer"),
            }
            _log({"event": "turn_done", **result})
            results.append(result)
        _log({"event": "trace_complete", "results": results})


if __name__ == "__main__":
    main()
