from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BATCH_TASK_FILES = ("started.json", "summary.json")
PAGE_FILES = (
    "context_built.json",
    "provider_decision.json",
    "provider_request.json",
    "provider_result.json",
    "saved_version.json",
)
EDIT_FILES = PAGE_FILES


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def print_check(ok: bool, label: str, detail: str = "") -> None:
    prefix = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{prefix}] {label}{suffix}")


def detect_kind(task_root: Path) -> str:
    if (task_root / "task").exists() or (task_root / "pages").exists():
        return "batch"
    if any((task_root / name).exists() for name in EDIT_FILES):
        return "edit"
    raise FileNotFoundError(f"Unable to detect artifact kind under {task_root}")


def expected_batch_dirs(summary: dict) -> tuple[set[str], set[str]]:
    success_dirs: set[str] = set()
    failed_dirs: set[str] = set()
    for row in summary.get("event", {}).get("page_results", []):
        page_id = row.get("page_id")
        page_order_index = row.get("page_order_index")
        if not page_id or page_order_index is None:
            continue
        dirname = f"page-{int(page_order_index):03d}-{page_id}"
        if row.get("error"):
            failed_dirs.add(dirname)
        else:
            success_dirs.add(dirname)
    return success_dirs, failed_dirs


def check_batch(task_root: Path) -> bool:
    ok = True
    task_dir = task_root / "task"
    pages_dir = task_root / "pages"

    for name in BATCH_TASK_FILES:
        exists = (task_dir / name).exists()
        print_check(exists, f"task/{name}")
        ok &= exists

    page_dirs = sorted(path for path in pages_dir.glob("page-*") if path.is_dir())
    print_check(bool(page_dirs), "pages/page-* directories", f"count={len(page_dirs)}")
    ok &= bool(page_dirs)

    summary = load_json(task_dir / "summary.json") if (task_dir / "summary.json").exists() else {}
    event = summary.get("event", {})
    if event:
        status = event.get("status")
        completed = event.get("completed")
        failed = event.get("failed")
        print(f"Batch summary: status={status} completed={completed} failed={failed}")

    success_dirs, failed_dirs = expected_batch_dirs(summary)
    if success_dirs or failed_dirs:
        missing_dirs = (success_dirs | failed_dirs) - {path.name for path in page_dirs}
        print_check(not missing_dirs, "page directories match summary", ", ".join(sorted(missing_dirs)))
        ok &= not missing_dirs

    for page_dir in page_dirs:
        if page_dir.name in failed_dirs:
            required_files = ("provider_result.json",)
            mode_detail = "failed-page minimum"
        else:
            required_files = PAGE_FILES
            mode_detail = "success-page full set"

        page_ok = True
        for name in required_files:
            exists = (page_dir / name).exists()
            print_check(exists, f"{page_dir.name}/{name}", mode_detail)
            page_ok &= exists

        provider_result_path = page_dir / "provider_result.json"
        if provider_result_path.exists():
            provider_result = load_json(provider_result_path)
            error_stage = provider_result.get("event", {}).get("error_stage")
            print(f"  {page_dir.name}: error_stage={error_stage}")

        saved_version_path = page_dir / "saved_version.json"
        if saved_version_path.exists():
            saved_version = load_json(saved_version_path)
            version = saved_version.get("event", {}).get("version_number")
            print(f"  {page_dir.name}: version={version}")

        ok &= page_ok

    return ok


def check_edit(task_root: Path) -> bool:
    ok = True
    for name in EDIT_FILES:
        exists = (task_root / name).exists()
        print_check(exists, name)
        ok &= exists

    if (task_root / "context_built.json").exists():
        context = load_json(task_root / "context_built.json")
        snapshot_source = context.get("event", {}).get("snapshot_source")
        print(f"Edit context: snapshot_source={snapshot_source}")

    if (task_root / "provider_result.json").exists():
        provider_result = load_json(task_root / "provider_result.json")
        error_stage = provider_result.get("event", {}).get("error_stage")
        print(f"Edit provider result: error_stage={error_stage}")

    if (task_root / "saved_version.json").exists():
        saved_version = load_json(task_root / "saved_version.json")
        trace = saved_version.get("trace", {})
        event = saved_version.get("event", {})
        print(
            "Edit saved version: "
            f"page_id={trace.get('page_id')} "
            f"source_version={trace.get('source_version_number')} "
            f"new_version={event.get('version_number')}"
        )

    return ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate restyle debug artifacts.")
    parser.add_argument("task_id", help="Task ID under data/debug/restyle-context")
    parser.add_argument(
        "--kind",
        choices=("auto", "batch", "edit"),
        default="auto",
        help="Artifact layout to validate",
    )
    parser.add_argument(
        "--debug-root",
        default="data/debug/restyle-context",
        help="Host debug root directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_root = Path(args.debug_root).expanduser().resolve() / args.task_id
    if not task_root.exists():
        print(f"Artifact directory not found: {task_root}", file=sys.stderr)
        return 1

    try:
        kind = args.kind if args.kind != "auto" else detect_kind(task_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Task: {args.task_id}")
    print(f"Kind: {kind}")
    print(f"Root: {task_root}")

    ok = check_batch(task_root) if kind == "batch" else check_edit(task_root)
    print(f"Result: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
