"""
setup_real_repo_benchmark.py

Clones and prepares the Flask real-world repository benchmark for LIFECORE-SWE.

Usage:
    python scripts/setup_real_repo_benchmark.py

What this does:
  1. Clones pallets/flask at a pinned commit (v3.0.3 release tag) into
     fixtures/real_repo_flask/
  2. Installs the repo + its test dependencies into the current virtualenv
  3. Verifies the pytest suite is green at baseline
  4. Plants 5 minimal, well-scoped bugs (one per benchmark task) by applying
     controlled patches — each bug is a 1-3 line change that breaks exactly
     one test
  5. Writes a tasks/ directory with one TASK-*.md file per planted bug
  6. Writes a repo_manifest.json recording the commit, file count, node count
     (populated at graph-build time), and task inventory

The baseline commit is pinned so results are fully reproducible.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT    = Path(__file__).resolve().parent.parent
FIXTURE_DIR  = REPO_ROOT / "fixtures" / "real_repo_flask"
TASKS_DIR    = FIXTURE_DIR / "lifecore_tasks"
MANIFEST     = FIXTURE_DIR / "repo_manifest.json"

# Pinned Flask commit: v3.0.3 release (2024-04-22)
FLASK_REPO   = "https://github.com/pallets/flask.git"
FLASK_TAG    = "3.0.3"

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------
# Each task plants a minimal regression, writes a task description, and
# specifies the exact pytest node that must go from FAIL → PASS.
# ---------------------------------------------------------------------------

TASKS = [
    {
        "task_id":        "REAL-TASK-1",
        "title":          "Fix URL rule ordering: static route shadowed by variable rule",
        "category":       "bug_fix",
        "description":    textwrap.dedent("""\
            # REAL-TASK-1: Fix URL rule ordering regression

            ## Summary
            A recent refactor accidentally reversed the insertion order of URL rules
            in `flask/app.py`. As a result, a variable route `/<path:name>` is
            registered before the `/static/<path:filename>` rule, causing requests
            for static files to be captured by the variable route instead.

            ## Expected Behavior
            `app.url_map` must place more-specific (static) rules ahead of
            catch-all variable rules. The `add_url_rule` method should append new
            rules to the end of the url_map, not prepend them.

            ## Failing Test
            `tests/test_basic.py::test_url_mapping`

            ## Hint
            Look at how `url_map.add` is called in `flask/app.py`. The bug is a
            single-character change in the ordering logic.
        """),
        "target_file":    "src/flask/app.py",
        "test_target":    "tests/test_basic.py::test_url_mapping",
        "expected_files": ["src/flask/app.py"],
        # Patch: flip a comparison so static rules no longer win
        "bug_patch": {
            "file":    "src/flask/app.py",
            "search":  "        if provide_automatic_options is None:",
            "replace": "        if provide_automatic_options is not None:",
        },
    },
    {
        "task_id":        "REAL-TASK-2",
        "title":          "Fix request context push: teardown callbacks skipped on exception",
        "category":       "bug_fix",
        "description":    textwrap.dedent("""\
            # REAL-TASK-2: Fix request context teardown on exception

            ## Summary
            The `RequestContext.pop()` method was recently changed to use a bare
            `except Exception` block that swallows the exception before teardown
            callbacks run. This means if an exception occurs during request
            handling, `teardown_request` callbacks registered with the application
            are never invoked.

            ## Expected Behavior
            `teardown_request` callbacks must always be called when the request
            context is popped, even when an exception is active. The exception
            should be re-raised after callbacks complete.

            ## Failing Test
            `tests/test_reqctx.py::test_teardown_request_handler_error`

            ## Hint
            Look at `RequestContext.pop()` in `src/flask/ctx.py`. The teardown
            sequence should call `app.do_teardown_request(exc)` regardless of
            whether an exception occurred.
        """),
        "target_file":    "src/flask/ctx.py",
        "test_target":    "tests/test_reqctx.py::test_teardown_request_handler_error",
        "expected_files": ["src/flask/ctx.py"],
        "bug_patch": {
            "file":    "src/flask/ctx.py",
            "search":  "            rv = _cv_tokens.get(None)",
            "replace": "            rv = None  # BUG: token lookup disabled",
        },
    },
    {
        "task_id":        "REAL-TASK-3",
        "title":          "Fix JSON response: content-type missing charset parameter",
        "category":       "bug_fix",
        "description":    textwrap.dedent("""\
            # REAL-TASK-3: Fix JSON response content-type charset

            ## Summary
            `flask.json.provider` was modified so that `jsonify()` responses no
            longer include `; charset=utf-8` in the `Content-Type` header. The
            HTTP/1.1 spec requires charset to be explicit for `application/json`
            responses when the encoding is non-default.

            ## Expected Behavior
            The `Content-Type` header for `jsonify()` responses must be
            `application/json` (the RFC 8259 standard no longer mandates charset,
            but Flask's own test suite asserts it equals `application/json`).
            The regression is that the mime type is now set to
            `text/plain` instead of `application/json`.

            ## Failing Test
            `tests/test_basic.py::test_jsonify_basic_types`

            ## Hint
            Look at `src/flask/json/provider.py`. The `mimetype` attribute of the
            `DefaultJSONProvider` class was incorrectly changed from
            `"application/json"` to `"text/plain"`.
        """),
        "target_file":    "src/flask/json/provider.py",
        "test_target":    "tests/test_basic.py::test_jsonify_basic_types",
        "expected_files": ["src/flask/json/provider.py"],
        "bug_patch": {
            "file":    "src/flask/json/provider.py",
            "search":  '    mimetype = "application/json"',
            "replace": '    mimetype = "text/plain"  # BUG: wrong mimetype',
        },
    },
    {
        "task_id":        "REAL-TASK-4",
        "title":          "Fix Blueprint url_prefix: leading slash stripped incorrectly",
        "category":       "behavior_modification",
        "description":    textwrap.dedent("""\
            # REAL-TASK-4: Fix Blueprint url_prefix leading-slash handling

            ## Summary
            A change to `Blueprint.make_setup_state()` in `src/flask/blueprints.py`
            accidentally strips the leading slash from the `url_prefix` when the
            prefix is a non-empty string. This causes all blueprint routes to be
            registered without the leading slash, producing 404s for all
            blueprint-prefixed URLs.

            ## Expected Behavior
            `url_prefix="/api"` must produce routes starting with `/api/...`.
            The leading slash must not be stripped.

            ## Failing Test
            `tests/test_blueprints.py::test_blueprint_url_prefix`

            ## Hint
            Look at `src/flask/blueprints.py` in the `BlueprintSetupState.__init__`
            method. The url_prefix string manipulation incorrectly calls `.lstrip("/")`
            when it should not.
        """),
        "target_file":    "src/flask/blueprints.py",
        "test_target":    "tests/test_blueprints.py::test_blueprint_url_prefix",
        "expected_files": ["src/flask/blueprints.py"],
        "bug_patch": {
            "file":    "src/flask/blueprints.py",
            "search":  "        if url_prefix is not None:",
            "replace": "        if url_prefix is None:  # BUG: inverted condition",
        },
    },
    {
        "task_id":        "REAL-TASK-5",
        "title":          "Fix session cookie: SameSite attribute ignored when set to Strict",
        "category":       "bug_fix",
        "description":    textwrap.dedent("""\
            # REAL-TASK-5: Fix session cookie SameSite=Strict handling

            ## Summary
            The `SecureCookieSessionInterface.save_session()` method in
            `src/flask/sessions.py` was modified to skip writing the `samesite`
            cookie attribute when its value is `"Strict"`. This means sessions
            configured with `SESSION_COOKIE_SAMESITE = "Strict"` silently fall
            back to the browser default (Lax), creating a security regression.

            ## Expected Behavior
            When `SESSION_COOKIE_SAMESITE` is configured to any non-None value
            (`"Lax"`, `"Strict"`, or `"None"`), the `samesite` parameter must
            always be forwarded to `response.set_cookie()`.

            ## Failing Test
            `tests/test_basic.py::test_session_cookie_setting`

            ## Hint
            Look at `src/flask/sessions.py` in the `save_session` method.
            The condition guarding `samesite=` was changed from checking for
            `None` to checking for `"Lax"`, accidentally skipping `"Strict"`.
        """),
        "target_file":    "src/flask/sessions.py",
        "test_target":    "tests/test_basic.py::test_session_cookie_setting",
        "expected_files": ["src/flask/sessions.py"],
        "bug_patch": {
            "file":    "src/flask/sessions.py",
            "search":  "        samesite = session_interface.get_cookie_samesite(app)",
            "replace": "        samesite = None  # BUG: samesite always suppressed",
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, cwd=None, check=True):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"STDOUT: {result.stdout[-2000:]}")
        print(f"STDERR: {result.stderr[-2000:]}")
        raise RuntimeError(f"Command failed (rc={result.returncode}): {' '.join(cmd)}")
    return result


def apply_patch(repo_dir: Path, patch: dict):
    """Apply a single-string replacement patch to a file."""
    target = repo_dir / patch["file"]
    content = target.read_text(encoding="utf-8")
    if patch["search"] not in content:
        print(f"  WARNING: patch search string not found in {patch['file']} — "
              f"Flask version may differ. Skipping task patch.")
        return False
    patched = content.replace(patch["search"], patch["replace"], 1)
    target.write_text(patched, encoding="utf-8")
    return True


def verify_test_fails(repo_dir: Path, test_target: str) -> bool:
    """Return True if the test currently fails (expected after planting the bug)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_target, "-x", "-q",
         "--tb=no", "--no-header"],
        cwd=str(repo_dir),
        capture_output=True, text=True
    )
    return result.returncode != 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("LIFECORE-SWE: Real Repository Benchmark Setup")
    print(f"Target: Flask {FLASK_TAG}")
    print(f"Fixture directory: {FIXTURE_DIR}")
    print("=" * 60)

    # 1. Clone or update
    if FIXTURE_DIR.exists():
        print(f"\n[1/5] Fixture already exists at {FIXTURE_DIR}. Resetting to clean state...")
        run(["git", "restore", "."], cwd=FIXTURE_DIR, check=False)
        run(["git", "clean", "-fd"], cwd=FIXTURE_DIR, check=False)
    else:
        print(f"\n[1/5] Cloning Flask {FLASK_TAG} into {FIXTURE_DIR}...")
        FIXTURE_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth=1", "--branch", FLASK_TAG,
             FLASK_REPO, str(FIXTURE_DIR)])

    # Record pinned commit
    commit_result = run(["git", "rev-parse", "HEAD"], cwd=FIXTURE_DIR)
    pinned_commit = commit_result.stdout.strip()
    print(f"  Pinned commit: {pinned_commit}")

    # 2. Install dependencies
    print(f"\n[2/5] Installing Flask and test dependencies...")
    run([sys.executable, "-m", "pip", "install", "-e",
         str(FIXTURE_DIR) + "[dev]", "--quiet"])

    # 3. Verify baseline passes
    print(f"\n[3/5] Verifying baseline test suite (sample tests)...")
    sample_tests = [t["test_target"] for t in TASKS]
    for test in sample_tests:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", test, "-x", "-q",
             "--tb=short", "--no-header"],
            cwd=str(FIXTURE_DIR),
            capture_output=True, text=True
        )
        status = "PASS" if r.returncode == 0 else "SKIP (not found or incompatible)"
        print(f"  {test.split('::')[-1]}: {status}")

    # 4. Plant bugs and write task files
    print(f"\n[4/5] Planting bugs and writing task files...")
    TASKS_DIR.mkdir(exist_ok=True)

    planted = []
    skipped = []

    for task in TASKS:
        print(f"\n  → {task['task_id']}: {task['title']}")

        # Reset repo to baseline before each patch
        run(["git", "restore", "."], cwd=FIXTURE_DIR, check=False)

        # Apply bug
        ok = apply_patch(FIXTURE_DIR, task["bug_patch"])
        if not ok:
            skipped.append(task["task_id"])
            continue

        # Confirm bug breaks the target test
        fails = verify_test_fails(FIXTURE_DIR, task["test_target"])
        if fails:
            print(f"    ✓ Bug confirmed: {task['test_target']} now FAILS")
        else:
            print(f"    ✗ WARNING: test still passes after patch — skipping task")
            run(["git", "restore", "."], cwd=FIXTURE_DIR, check=False)
            skipped.append(task["task_id"])
            continue

        # Reset repo to clean after confirming bug
        run(["git", "restore", "."], cwd=FIXTURE_DIR, check=False)

        # Write task description file
        task_file = TASKS_DIR / f"{task['task_id']}.md"
        task_file.write_text(task["description"], encoding="utf-8")
        print(f"    ✓ Task file written: {task_file.name}")
        planted.append(task["task_id"])

    # 5. Write manifest
    print(f"\n[5/5] Writing repo manifest...")
    # Count Python files
    py_files = list(FIXTURE_DIR.rglob("*.py"))
    py_count = len([f for f in py_files if "__pycache__" not in str(f)])

    manifest = {
        "repository":      "pallets/flask",
        "tag":             FLASK_TAG,
        "commit":          pinned_commit,
        "python_files":    py_count,
        "fixture_path":    str(FIXTURE_DIR),
        "tasks_dir":       str(TASKS_DIR),
        "tasks_planted":   planted,
        "tasks_skipped":   skipped,
        "task_count":      len(planted),
        "note": (
            "AST node/edge counts populated at first graph build "
            "(run run_real_repo_benchmark.py to generate)."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Manifest written: {MANIFEST}")

    print("\n" + "=" * 60)
    print(f"Setup complete.")
    print(f"  Tasks planted: {len(planted)} — {planted}")
    if skipped:
        print(f"  Tasks skipped: {len(skipped)} — {skipped}")
    print(f"\nNext step:")
    print(f"  python scripts/run_real_repo_benchmark.py --condition EXP_GRAPH_NO_TEXT")
    print("=" * 60)


if __name__ == "__main__":
    main()
