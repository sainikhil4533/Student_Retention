from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.auth_accounts import ensure_bootstrap_accounts, hash_password
from src.api.main import app
from src.db.database import SessionLocal
from src.db.repository import EventRepository


TEMP_USERNAME = "student.reset.990001"
TEMP_PASSWORD = "TempPass@123"
UPDATED_PASSWORD = "UpdatedPass@123"


def main() -> None:
    failures: list[str] = []

    with SessionLocal() as db:
        repository = EventRepository(db)
        ensure_bootstrap_accounts(repository)
        existing = repository.get_auth_account_by_username(TEMP_USERNAME)
        if existing is None:
            repository.create_auth_account(
                {
                    "username": TEMP_USERNAME,
                    "password_hash": hash_password(TEMP_PASSWORD),
                    "role": "student",
                    "student_id": 990001,
                    "display_name": "Reset Flow Student",
                    "institution_email": "student.reset.990001@retentionos.local",
                    "is_active": True,
                    "must_reset_password": True,
                }
            )
        else:
            repository.update_auth_account(
                int(existing.id),
                {
                    "password_hash": hash_password(TEMP_PASSWORD),
                    "must_reset_password": True,
                    "is_active": True,
                },
            )

    client = TestClient(app)

    admin_login = client.post("/auth/login", json={"username": "admin.retention", "password": "Admin@123"})
    admin_login.raise_for_status()
    admin_payload = admin_login.json()
    if admin_payload.get("password_reset_required") is not False:
      failures.append("Bootstrap admin account should log in without an immediate reset requirement.")

    temp_login = client.post("/auth/login", json={"username": TEMP_USERNAME, "password": TEMP_PASSWORD})
    temp_login.raise_for_status()
    temp_payload = temp_login.json()
    if temp_payload.get("password_reset_required") is not True:
        failures.append("Temporary password account should require password reset on login.")

    headers = {"Authorization": f"Bearer {temp_payload['access_token']}"}
    me_response = client.get("/auth/me", headers=headers)
    me_response.raise_for_status()
    if me_response.json().get("username") != TEMP_USERNAME:
        failures.append("Auth /me should return the authenticated username for institution accounts.")

    reset_response = client.post(
        "/auth/reset-password",
        json={"current_password": TEMP_PASSWORD, "new_password": UPDATED_PASSWORD},
        headers=headers,
    )
    reset_response.raise_for_status()
    reset_payload = reset_response.json()
    if reset_payload.get("password_reset_required") is not False:
        failures.append("Password reset response should clear the reset-required flag.")

    relogin = client.post("/auth/login", json={"username": TEMP_USERNAME, "password": UPDATED_PASSWORD})
    relogin.raise_for_status()
    relogin_payload = relogin.json()
    if relogin_payload.get("password_reset_required") is not False:
        failures.append("Account should no longer require reset after successful password update.")

    if failures:
        print("Frontend auth upgrade verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Frontend auth upgrade verification passed.")


if __name__ == "__main__":
    main()
