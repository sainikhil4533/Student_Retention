from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import func


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import SessionLocal
from src.db.models import StudentAcademicRecord


def main() -> None:
    db = SessionLocal()
    try:
        total_rows = db.query(func.count(StudentAcademicRecord.id)).scalar() or 0
        pending_i = (
            db.query(func.count(StudentAcademicRecord.id))
            .filter(StudentAcademicRecord.result_status == "Pending I-grade clearance")
            .scalar()
            or 0
        )
        pending_r = (
            db.query(func.count(StudentAcademicRecord.id))
            .filter(StudentAcademicRecord.result_status == "Pending R-grade clearance")
            .scalar()
            or 0
        )
        print(f"student_academic_records={int(total_rows)}")
        print(f"pending_i_grade_rows={int(pending_i)}")
        print(f"pending_r_grade_rows={int(pending_r)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
