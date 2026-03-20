"""Reassign bootstrap-owned resources to a real user account."""

import argparse
import importlib.util
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from models import db


def _load_m017_module():
    migration_path = BACKEND_DIR / 'migrations' / 'versions' / '017_auth_owner_backfill.py'
    spec = importlib.util.spec_from_file_location('m017_auth_owner_backfill', migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m017_module = _load_m017_module()


TABLES = ['projects', 'user_templates', 'materials', 'tasks', 'reference_files']


def _count_bootstrap_rows(conn):
    counts = {}
    for table_name in TABLES:
        row = conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM {table_name} WHERE owner_id = ?",
            (m017_module.BOOTSTRAP_USER_ID,),
        ).fetchone()
        counts[table_name] = row[0] if row else 0
    return counts


def _apply_reassign(conn, target_user_id: str):
    for table_name in TABLES:
        conn.exec_driver_sql(
            f"UPDATE {table_name} SET owner_id = ? WHERE owner_id = ?",
            (target_user_id, m017_module.BOOTSTRAP_USER_ID),
        )


def main():
    parser = argparse.ArgumentParser(description='Reassign bootstrap-owned resources to target user')
    parser.add_argument('--target-user-id', required=True, help='Target user id to receive bootstrap resources')
    parser.add_argument('--dry-run', action='store_true', help='Preview affected rows without writing changes')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        conn = db.engine.connect()
        tx = conn.begin()
        try:
            user = conn.exec_driver_sql(
                "SELECT id FROM users WHERE id = ?",
                (args.target_user_id,),
            ).fetchone()
            if not user:
                raise SystemExit(f"target user not found: {args.target_user_id}")

            counts = _count_bootstrap_rows(conn)
            if args.dry_run:
                print('dry-run mode, no changes applied')
                for table_name, count in counts.items():
                    print(f"{table_name}: {count}")
                tx.rollback()
                return

            _apply_reassign(conn, args.target_user_id)
            tx.commit()

            print(f"reassigned bootstrap resources to {args.target_user_id}")
            for table_name, count in counts.items():
                print(f"{table_name}: {count}")
        finally:
            conn.close()


if __name__ == '__main__':
    main()
