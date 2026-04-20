from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import func


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import SessionLocal
from src.db.models import PredictionHistory, StudentWarningEvent
from src.db.repository import EventRepository


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        imported_profiles = repository.get_imported_student_profiles()
        imported_student_ids = [int(profile.student_id) for profile in imported_profiles]
        prediction_count = (
            db.query(func.count(PredictionHistory.id))
            .filter(PredictionHistory.student_id.in_(imported_student_ids))
            .scalar()
        )
        distinct_prediction_students = (
            db.query(func.count(func.distinct(PredictionHistory.student_id)))
            .filter(PredictionHistory.student_id.in_(imported_student_ids))
            .scalar()
        )
        warning_count = (
            db.query(func.count(StudentWarningEvent.id))
            .filter(StudentWarningEvent.student_id.in_(imported_student_ids))
            .scalar()
        )
        print(f"imported_students={len(imported_profiles)}")
        print(f"prediction_history_rows={int(prediction_count or 0)}")
        print(f"students_with_predictions={int(distinct_prediction_students or 0)}")
        print(f"student_warning_events={int(warning_count or 0)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
