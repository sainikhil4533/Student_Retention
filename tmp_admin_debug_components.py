from __future__ import annotations

from time import perf_counter

from src.api.copilot_tools import _build_academic_scope_summary
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def main() -> None:
    start = perf_counter()
    db = SessionLocal()
    print("components:start", flush=True)
    try:
        repository = EventRepository(db)

        mark = perf_counter()
        profiles = repository.get_imported_student_profiles()
        print(f"components:profiles {perf_counter() - mark:.2f}s count={len(profiles)}", flush=True)

        mark = perf_counter()
        history = repository.get_all_prediction_history()
        print(f"components:history {perf_counter() - mark:.2f}s count={len(history)}", flush=True)

        mark = perf_counter()
        summary = _build_academic_scope_summary(repository=repository)
        print(
            "components:academic_summary "
            f"{perf_counter() - mark:.2f}s "
            f"i_grade={summary['total_students_with_i_grade_risk']} "
            f"r_grade={summary['total_students_with_r_grade_risk']}",
            flush=True,
        )
    finally:
        db.close()
        print(f"components:done {perf_counter() - start:.2f}s", flush=True)


if __name__ == "__main__":
    main()
