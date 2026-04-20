from __future__ import annotations

import sys
from time import perf_counter

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def main() -> None:
    start = perf_counter()
    print("debug:start", flush=True)
    db = SessionLocal()
    print(f"debug:db_open {perf_counter() - start:.2f}s", flush=True)
    try:
        repository = EventRepository(db)
        auth = AuthContext(
            role="admin",
            subject="admin.retention",
            display_name="Retention Admin",
            auth_provider="local_institution_account",
        )
        prompt = sys.argv[1] if len(sys.argv) > 1 else "stats"
        profiles = repository.get_imported_student_profiles()
        print(f"debug:profiles {perf_counter() - start:.2f}s count={len(profiles)}", flush=True)
        query_plan = plan_copilot_query(
            role=auth.role,
            message=prompt,
            session_messages=[],
            profiles=profiles,
        )
        print(f"debug:plan {perf_counter() - start:.2f}s {query_plan.to_dict()}", flush=True)
        memory = resolve_copilot_memory_context(message=prompt, session_messages=[])
        answer, tools_used, limitations, memory_context = generate_grounded_copilot_answer(
            auth=auth,
            repository=repository,
            message=prompt,
            session_messages=[],
            memory=memory,
            query_plan=query_plan.to_dict(),
        )
        print(f"debug:answer {perf_counter() - start:.2f}s", flush=True)
        print(answer, flush=True)
        print(tools_used, flush=True)
        print(limitations, flush=True)
        print(memory_context, flush=True)
    finally:
        db.close()
        print(f"debug:done {perf_counter() - start:.2f}s", flush=True)


if __name__ == "__main__":
    main()
