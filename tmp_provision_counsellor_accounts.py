from src.api.auth_accounts import provision_counsellor_auth_accounts
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        profiles = repository.get_imported_student_profiles()
        created = provision_counsellor_auth_accounts(
            repository,
            profiles=profiles,
            commit=True,
        )
        print(
            "Counsellor account backfill completed. "
            f"imported_profiles={len(profiles)} counsellor_accounts_created={created}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
