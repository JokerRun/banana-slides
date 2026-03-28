from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def print_check(ok: bool, label: str, detail: str = "") -> None:
    prefix = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{prefix}] {label}{suffix}")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def host_upload_path(value: str | None, uploads_root: Path) -> Path | None:
    if not value:
        return None
    if value.startswith("/app/uploads/"):
        suffix = value.removeprefix("/app/uploads/")
        return uploads_root / suffix
    path = Path(value)
    if path.is_absolute():
        return path
    return uploads_root / value


def row_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and cross-check restyle DB state.")
    parser.add_argument("--project-id", required=True, help="Project ID to inspect")
    parser.add_argument("--db", default="data/instance/database.db", help="SQLite database path")
    parser.add_argument("--uploads-root", default="data/uploads", help="Host uploads root")
    parser.add_argument("--debug-root", default="data/debug/restyle-context", help="Host debug root")
    parser.add_argument("--first-pass-task-id", help="Batch restyle task ID")
    parser.add_argument("--edit-task-id", help="Single-page edit task ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    uploads_root = Path(args.uploads_root).expanduser().resolve()
    debug_root = Path(args.debug_root).expanduser().resolve()

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    ok = True
    conn = connect_readonly(db_path)
    try:
        project = conn.execute(
            "SELECT id, creation_type, status, restyle_prompt FROM projects WHERE id=?",
            (args.project_id,),
        ).fetchone()
        print_check(project is not None, "project exists", args.project_id)
        if not project:
            return 1

        print(
            "Project: "
            f"id={project['id']} type={project['creation_type']} status={project['status']} "
            f"restyle_prompt={'yes' if project['restyle_prompt'] else 'no'}"
        )

        pages = row_dicts(
            conn.execute(
                """
                SELECT id, order_index, status, generated_image_path, restyle_base_prompt_snapshot
                FROM pages
                WHERE project_id=?
                ORDER BY order_index
                """,
                (args.project_id,),
            )
        )
        print_check(bool(pages), "pages found", f"count={len(pages)}")
        ok &= bool(pages)

        tasks = row_dicts(
            conn.execute(
                """
                SELECT id, task_type, status, created_at
                FROM tasks
                WHERE project_id=?
                ORDER BY created_at
                """,
                (args.project_id,),
            )
        )
        print_check(bool(tasks), "tasks found", f"count={len(tasks)}")
        ok &= bool(tasks)

        versions = row_dicts(
            conn.execute(
                """
                SELECT piv.page_id, piv.version_number, piv.image_path, piv.is_current, p.order_index
                FROM page_image_versions piv
                JOIN pages p ON p.id = piv.page_id
                WHERE p.project_id=?
                ORDER BY p.order_index, piv.version_number
                """,
                (args.project_id,),
            )
        )
        print_check(bool(versions), "page_image_versions found", f"count={len(versions)}")
        ok &= bool(versions)

        print("Pages:")
        pages_by_id = {row["id"]: row for row in pages}
        current_versions: dict[str, dict] = {}
        for version in versions:
            if version["is_current"]:
                current_versions[version["page_id"]] = version

        for page in pages:
            snapshot_present = bool(page["restyle_base_prompt_snapshot"])
            current_version = current_versions.get(page["id"])
            print(
                "  "
                f"page[{page['order_index']}] id={page['id']} status={page['status']} "
                f"generated={page['generated_image_path']} snapshot={'yes' if snapshot_present else 'no'} "
                f"current_version={current_version['version_number'] if current_version else None}"
            )

            if page["generated_image_path"] and current_version:
                matches = page["generated_image_path"] == current_version["image_path"]
                print_check(matches, f"page[{page['order_index']}] current image matches current version")
                ok &= matches

        print("Tasks:")
        tasks_by_id = {row["id"]: row for row in tasks}
        for task in tasks:
            print(f"  {task['id']} type={task['task_type']} status={task['status']}")

        print("Versions:")
        versions_by_page: dict[str, list[dict]] = {}
        for version in versions:
            versions_by_page.setdefault(version["page_id"], []).append(version)
            file_path = host_upload_path(version["image_path"], uploads_root)
            exists = bool(file_path) and file_path.exists()
            print(
                "  "
                f"page[{version['order_index']}] v{version['version_number']} current={version['is_current']} "
                f"exists={'yes' if exists else 'no'} path={version['image_path']}"
            )
            print_check(exists, f"page[{version['order_index']}] v{version['version_number']} file exists")
            ok &= exists

        if args.first_pass_task_id:
            task = tasks_by_id.get(args.first_pass_task_id)
            print_check(task is not None, "first-pass task exists in DB", args.first_pass_task_id)
            ok &= task is not None
            if task:
                summary_path = debug_root / args.first_pass_task_id / "task" / "summary.json"
                print_check(summary_path.exists(), "first-pass summary.json exists", str(summary_path))
                ok &= summary_path.exists()
                if summary_path.exists():
                    summary = load_json(summary_path)
                    summary_status = summary.get("event", {}).get("status")
                    matches = summary_status == task["status"]
                    print_check(matches, "first-pass DB status matches summary", f"db={task['status']} debug={summary_status}")
                    ok &= matches

        if args.edit_task_id:
            task = tasks_by_id.get(args.edit_task_id)
            print_check(task is not None, "edit task exists in DB", args.edit_task_id)
            ok &= task is not None
            if task:
                task_type_ok = task["task_type"] == "EDIT_PAGE_IMAGE"
                print_check(task_type_ok, "edit task type is EDIT_PAGE_IMAGE", task["task_type"])
                ok &= task_type_ok

                saved_version_path = debug_root / args.edit_task_id / "saved_version.json"
                print_check(saved_version_path.exists(), "edit saved_version.json exists", str(saved_version_path))
                ok &= saved_version_path.exists()
                if saved_version_path.exists():
                    saved_version = load_json(saved_version_path)
                    trace = saved_version.get("trace", {})
                    event = saved_version.get("event", {})
                    page_id = trace.get("page_id")
                    new_version = event.get("version_number")
                    source_version = trace.get("source_version_number")
                    image_path = event.get("image_path")

                    print(
                        "Edit debug: "
                        f"page_id={page_id} source_version={source_version} "
                        f"new_version={new_version} image_path={image_path}"
                    )

                    page_versions = versions_by_page.get(page_id or "", [])
                    version_row = next((row for row in page_versions if row["version_number"] == new_version), None)
                    print_check(version_row is not None, "edit version exists in DB", f"page_id={page_id} version={new_version}")
                    ok &= version_row is not None
                    if version_row:
                        current_ok = bool(version_row["is_current"])
                        print_check(current_ok, "edit version is current in DB")
                        ok &= current_ok

                        path_ok = version_row["image_path"] == image_path
                        print_check(path_ok, "edit image path matches DB", f"db={version_row['image_path']} debug={image_path}")
                        ok &= path_ok

                    if page_id and page_id in pages_by_id:
                        page_row = pages_by_id[page_id]
                        path_ok = page_row["generated_image_path"] == image_path
                        print_check(path_ok, "page.generated_image_path matches edit debug")
                        ok &= path_ok

                    if source_version is not None and new_version is not None:
                        increment_ok = int(new_version) == int(source_version) + 1
                        print_check(increment_ok, "edit version increments from source", f"source={source_version} new={new_version}")
                        ok &= increment_ok

        print(f"Result: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
