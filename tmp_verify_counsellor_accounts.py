from src.db.database import SessionLocal
from src.db.models import AuthAccount


def main() -> None:
    db = SessionLocal()
    try:
        counsellors = (
            db.query(AuthAccount)
            .filter(AuthAccount.role == "counsellor")
            .order_by(AuthAccount.username.asc())
            .all()
        )
        print(f"counsellor_accounts={len(counsellors)}")
        for account in counsellors[:10]:
            print(
                f"username={account.username} display_name={account.display_name} "
                f"email={account.institution_email} must_reset={account.must_reset_password}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
