from __future__ import annotations

from pathlib import Path
import json
import sys

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


BASE_URL = "http://127.0.0.1:8000"
DEMO_DIR = PROJECT_ROOT / "demo"
REQUEST_TIMEOUT_SECONDS = 90
DEMO_ADMIN_USERNAME = "admin.retention"
DEMO_ADMIN_PASSWORD = "Admin@123"


def get_auth_headers() -> dict[str, str]:
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": DEMO_ADMIN_USERNAME, "password": DEMO_ADMIN_PASSWORD},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def load_json(filename: str) -> list[dict]:
    return json.loads((DEMO_DIR / filename).read_text(encoding="utf-8"))


def index_by_student(items: list[dict], nested_key: str | None = None) -> dict[int, dict]:
    indexed: dict[int, dict] = {}
    for item in items:
        student_id = int(item["student_id"])
        indexed[student_id] = item[nested_key] if nested_key else item
    return indexed


def post_json(path: str, payload: dict) -> dict:
    response = requests.post(
        f"{BASE_URL}{path}",
        json=payload,
        headers=get_auth_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def put_json(path: str, payload: dict) -> dict:
    response = requests.put(
        f"{BASE_URL}{path}",
        json=payload,
        headers=get_auth_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def get_json(path: str) -> dict:
    response = requests.get(
        f"{BASE_URL}{path}",
        headers=get_auth_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    students = load_json("sample_students.json")
    lms_records = index_by_student(load_json("sample_lms.json"))
    erp_records = index_by_student(load_json("sample_erp.json"), nested_key="erp_event")
    finance_records = index_by_student(load_json("sample_finance.json"), nested_key="finance_event")

    print("Running demo flow against the live API...")
    print()

    for student in students:
        student_id = int(student["student_id"])
        scenario = student["scenario"]
        demographics = student["demographics"]

        print(f"=== Student {student_id} ({scenario}) ===")
        profile_result = put_json(f"/profiles/{student_id}", demographics)
        print("Profile upsert:", profile_result)

        for lms_event in lms_records[student_id]["events"]:
            result = post_json("/ingest/lms", lms_event)
            print("LMS ingest:", result)

        finance_result = post_json("/ingest/finance", finance_records[student_id])
        print("Finance ingest:", finance_result)

        erp_result = post_json("/ingest/erp", erp_records[student_id])
        print("ERP ingest:", erp_result)

        latest_result = get_json(f"/score/latest/{student_id}")
        print("Latest stored prediction:", json.dumps(latest_result, indent=2))

        history_result = get_json(f"/score/history/{student_id}")
        print("History count:", len(history_result["history"]))
        print()


if __name__ == "__main__":
    main()
