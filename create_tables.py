"""
create_tables.py
─────────────────
One-off script to create all database tables (users, workspaces, tasks, etc.)
in whatever database DATABASE_URL points to.

USAGE:
    1. Make sure DATABASE_URL is set in your environment (or in a .env file
       in this same folder — it will be picked up automatically since the
       app already uses python-dotenv / pydantic-settings).
    2. Run this from your project root (same folder as requirements.txt):
           python create_tables.py
    3. After it succeeds, also run:
           alembic upgrade head
       to apply the incremental migrations (slack columns, freelancer slug, etc.)
"""

from app.database import Base, engine
import app.models  # noqa: F401  (import registers all model classes on Base)


def main() -> None:
    print("Connecting and creating tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully (or already existed).")

    # Quick sanity check: list what tables now exist
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nTables now in database ({len(tables)}):")
    for t in sorted(tables):
        print(f"  - {t}")


if __name__ == "__main__":
    main()
