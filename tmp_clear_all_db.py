from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import delete, func, select


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import Base, SessionLocal  # noqa: E402
from src.db import models  # noqa: F401,E402


def main() -> None:
    with SessionLocal() as session:
        row_counts_before: list[tuple[str, int]] = []
        for table in Base.metadata.sorted_tables:
            count = session.execute(select(func.count()).select_from(table)).scalar_one()
            row_counts_before.append((table.name, int(count)))

        for table in reversed(Base.metadata.sorted_tables):
            session.execute(delete(table))

        session.commit()

    print("Cleared all rows from configured database tables.")
    for table_name, count in row_counts_before:
        if count:
            print(f"{table_name}: deleted {count} rows")


if __name__ == "__main__":
    main()
