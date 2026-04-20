from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.api.dependencies import prediction_service
from src.api.scoring_service import score_student_from_db
from src.db.database import SessionLocal, engine
from src.db.repository import EventRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score imported students already present in the database."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Score students even if they already have prediction history.",
    )
    parser.add_argument(
        "--allow-gemini",
        action="store_true",
        help="Allow Gemini-backed AI insights during scoring. Default bulk mode disables Gemini and uses fallback insights for speed and stability.",
    )
    return parser.parse_args()


def load_imported_students() -> list[tuple[int, str]]:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        return [
            (
                int(profile.student_id),
                str(getattr(profile, "external_student_ref", "") or profile.student_id),
            )
            for profile in repository.get_imported_student_profiles()
        ]
    finally:
        db.close()


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()
    if not args.allow_gemini:
        os.environ["GEMINI_API_KEY"] = ""

    students = load_imported_students()
    total_students = len(students)
    success_count = 0
    skipped_count = 0
    failed_count = 0
    failures: list[str] = []

    print(
        f"[score.imported] start total_students={total_students} "
        f"force={args.force} allow_gemini={args.allow_gemini}",
        flush=True,
    )

    for index, (student_id, external_ref) in enumerate(students, start=1):
        db = SessionLocal()
        try:
            repository = EventRepository(db)
            latest_prediction = repository.get_latest_prediction_for_student(student_id)
            if latest_prediction is not None and not args.force:
                skipped_count += 1
                continue

            result = score_student_from_db(
                student_id=student_id,
                db=db,
                prediction_service=prediction_service,
            )
            success_count += 1
            if index % 25 == 0 or index == total_students:
                print(
                    "[score.imported] progress "
                    f"processed={index}/{total_students} "
                    f"scored={success_count} skipped={skipped_count} failed={failed_count} "
                    f"last_student={external_ref} "
                    f"prediction_id={result.get('prediction_history_id')} "
                    f"elapsed={time.perf_counter() - started_at:.2f}s",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed_count += 1
            failures.append(f"{external_ref}: {exc}")
            engine.dispose()
            print(
                f"[score.imported] failure student={external_ref} error={exc}",
                flush=True,
            )
        finally:
            db.close()

    print(
        "[score.imported] completed "
        f"total_students={total_students} scored={success_count} skipped={skipped_count} "
        f"failed={failed_count} elapsed={time.perf_counter() - started_at:.2f}s",
        flush=True,
    )
    if failures:
        print("[score.imported] failures:", flush=True)
        for failure in failures:
            print(f"  - {failure}", flush=True)


if __name__ == "__main__":
    main()
