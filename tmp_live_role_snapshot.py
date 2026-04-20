from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import SessionLocal
from src.db.models import AuthAccount, StudentProfile


def main() -> None:
    db = SessionLocal()
    try:
        auth_rows = (
            db.query(AuthAccount)
            .order_by(AuthAccount.role.asc(), AuthAccount.username.asc())
            .all()
        )
        print("auth_accounts_sample:")
        for row in auth_rows[:15]:
            print(
                f"  username={row.username} role={row.role} student_id={row.student_id} "
                f"display_name={row.display_name} must_reset={row.must_reset_password}"
            )

        counsellor_names = sorted(
            {
                str(row.counsellor_name).strip()
                for row in db.query(StudentProfile).all()
                if str(row.counsellor_name or "").strip()
            }
        )
        print("distinct_counsellor_names:")
        for name in counsellor_names[:20]:
            print(f"  {name}")

        imported_students = (
            db.query(StudentProfile)
            .filter(StudentProfile.external_student_ref.is_not(None))
            .order_by(StudentProfile.student_id.asc())
            .all()
        )
        print("imported_student_usernames_sample:")
        for row in imported_students[:10]:
            print(
                f"  external_ref={row.external_student_ref} student_id={row.student_id} "
                f"student_email={row.student_email}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
