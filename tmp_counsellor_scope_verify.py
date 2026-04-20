from fastapi import HTTPException

from src.api.auth import AuthContext
from src.api.scope import ensure_student_scope_access, get_counsellor_scope_student_ids


class _Profile:
    def __init__(self, student_id: int) -> None:
        self.student_id = student_id


class _FakeRepository:
    def get_imported_student_profiles_for_counsellor_identity(self, *, subject: str, display_name: str | None = None):
        if subject == "counsellor.vignan":
            return [_Profile(101), _Profile(102), _Profile(103)]
        return []


def main() -> None:
    repository = _FakeRepository()
    counsellor_auth = AuthContext(role="counsellor", subject="counsellor.vignan", display_name="Counsellor Vignan")
    admin_auth = AuthContext(role="admin", subject="admin.retention")
    student_auth = AuthContext(role="student", subject="student.101", student_id=101)

    scoped_ids = get_counsellor_scope_student_ids(auth=counsellor_auth, repository=repository)
    assert scoped_ids == {101, 102, 103}

    ensure_student_scope_access(auth=counsellor_auth, repository=repository, student_id=101)
    ensure_student_scope_access(auth=admin_auth, repository=repository, student_id=999)
    ensure_student_scope_access(auth=student_auth, repository=repository, student_id=101)

    try:
        ensure_student_scope_access(auth=counsellor_auth, repository=repository, student_id=999)
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Counsellor should not access out-of-scope student 999.")

    try:
        ensure_student_scope_access(auth=student_auth, repository=repository, student_id=102)
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Student should not access another student's record.")

    print("Counsellor scope verification passed.")


if __name__ == "__main__":
    main()
