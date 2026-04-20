from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


REQUIRED_FILES = [
    "run_all.py",
    "start_system.bat",
    ".env.example",
    "docs/LOCAL_STARTUP_AND_READINESS_GUIDE.md",
    "docs/DEPLOYMENT_READINESS_CHECKLIST.md",
    "docs/FRONTEND_UAT_GUIDE.md",
    "src/api/main.py",
    "src/worker/runner.py",
    "frontend/package.json",
]

REQUIRED_ENV_KEYS = [
    "DATABASE_URL",
    "AUTH_SECRET_KEY",
    "GEMINI_MODEL",
    "GEMINI_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_FROM_EMAIL",
    "SMTP_PASSWORD",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    missing_files = [path for path in REQUIRED_FILES if not (PROJECT_ROOT / path).exists()]
    if missing_files:
        print("Local readiness check failed: missing required files.")
        for path in missing_files:
            print(f"- missing: {path}")
        return 1

    env_path = PROJECT_ROOT / ".env"
    env_values = parse_env_file(env_path)

    if not env_path.exists():
        print("Local readiness check warning: `.env` is missing.")
        print("Copy `.env.example` to `.env` and fill in real values before running the full stack.")
        return 1

    missing_keys = [key for key in REQUIRED_ENV_KEYS if not env_values.get(key)]
    if missing_keys:
        print("Local readiness check failed: `.env` is missing required keys.")
        for key in missing_keys:
            print(f"- missing env key: {key}")
        return 1

    auth_secret = env_values.get("AUTH_SECRET_KEY", "")
    if auth_secret in {"student-retention-2026", "replace_with_a_long_random_secret"}:
        print("Local readiness warning: AUTH_SECRET_KEY still looks like a default/demo value.")
        print("Rotate it before staging or production-style deployment.")

    database_url = env_values.get("DATABASE_URL", "")
    if "password" in database_url.lower():
        print("Local readiness warning: DATABASE_URL still looks like a template value.")

    print("Local readiness check passed.")
    print("Core files exist, `.env` is present, and required env keys were found.")
    print("Next steps:")
    print("- Start the stack with `python run_all.py --with-frontend` or `start_system.bat`.")
    print("- Use `docs/FRONTEND_UAT_GUIDE.md` for browser testing.")
    print("- Use `docs/DEPLOYMENT_READINESS_CHECKLIST.md` before any serious deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
