#!/usr/bin/env python3
"""Run MyMarketplace unit, integration and E2E tests in that order.

Run from any directory:  python run_tests.py
Only edit the CONFIGURATION section below; no CLI flags are required.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


# ============================ CONFIGURATION =============================

# Select the test layers to run. They always run in the order shown.
RUN_UNIT_TESTS = True
RUN_INTEGRATION_TESTS = True
RUN_E2E_TESTS = True

# The API is only required for E2E tests; integration tests use a fake API.
BACKEND = "prism"                 # "prism" or "real"
API_URL = "http://localhost:4010"  # Prism default; use :9999 if started with -p 9999
FRONTEND_URL = None               # None = automatically host ./frontend

# Paths to Chrome for Testing. Leave as None to use Selenium Manager.
# Example: r"D:\Tools\chrome-win64\chrome.exe"
CHROME_BINARY = r"D:\_PROJECTS\TOOLS\chrome_for_testing\chrome\158.0.8127.36\chrome.exe"
# Example: r"D:\Tools\chromedriver-win64\chromedriver.exe"
CHROMEDRIVER_PATH = r"D:\_PROJECTS\TOOLS\chrome_for_testing\chromedriver\158.0.8127.36\chromedriver.exe"

# Browser and pytest behavior.
SHOW_BROWSER = True               # False = headless Chrome
UI_TIMEOUT_SECONDS = 12
TRACE_BROWSER_SETUP = False        # True = print the [E2E setup] messages
STOP_ON_FIRST_TEST_FAILURE = True  # Adds pytest -x
STOP_AFTER_FAILED_STAGE = True   # If JS unit tests fail, skip browser tests

# Optional test credentials (mostly for BACKEND="real").
# Environment variables are preferable to hardcoding secrets in this file.
TEST_USERNAME = os.getenv("E2E_USERNAME")
TEST_PASSWORD = os.getenv("E2E_PASSWORD")

# Real backend writes are opt-in. Use a dedicated disposable test account.
ALLOW_CART_MUTATIONS = False
ALLOW_ACCOUNT_CHANGES = False
ALLOW_ACCOUNT_DELETION = False   # Permanently deletes the test account!

# Executables and report location.
NODE_EXECUTABLE = "node"          # Or an absolute path to node.exe
PYTHON_EXECUTABLE = sys.executable # Uses the current virtual environment
WRITE_JUNIT_REPORT = True
REPORT_DIR = "reports"

# =======================================================================

ROOT = Path(__file__).resolve().parent


def display_command(args: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def run_stage(label: str, command: list[str], env: dict[str, str]) -> tuple[int, float]:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}", flush=True)
    print(f"$ {display_command(command)}\n", flush=True)
    start = time.monotonic()
    try:
        # shell=False is intentional: paths containing spaces work on Windows.
        status = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    except FileNotFoundError as exc:
        print(f"ERROR: Executable not found: {command[0]!r}. {exc}", file=sys.stderr)
        status = 127
    elapsed = time.monotonic() - start
    print(f"\n{label}: {'PASS' if status == 0 else 'FAIL'} "
          f"(exit code {status}, {elapsed:.1f}s)", flush=True)
    return status, elapsed


def junit_counts(path: Path) -> dict[str, dict[str, int]]:
    """Split the one pytest run into integration/E2E counts for the summary."""
    counts = {
        "Integration": dict(passed=0, failed=0, skipped=0),
        "E2E": dict(passed=0, failed=0, skipped=0),
    }
    if not path.is_file():
        return counts
    try:
        for case in ET.parse(path).iter("testcase"):
            cls = case.get("classname", "").replace("/", ".").replace("\\", ".")
            layer = "Integration" if "integration" in cls.split(".") else "E2E"
            if case.find("failure") is not None or case.find("error") is not None:
                state = "failed"
            elif case.find("skipped") is not None:
                state = "skipped"
            else:
                state = "passed"
            counts[layer][state] += 1
    except (ET.ParseError, OSError) as exc:
        print(f"Warning: Could not read pytest report {path}: {exc}")
    return counts


def main() -> int:
    if BACKEND not in {"prism", "real"}:
        print('BACKEND must be "prism" or "real".', file=sys.stderr)
        return 2
    if not any((RUN_UNIT_TESTS, RUN_INTEGRATION_TESTS, RUN_E2E_TESTS)):
        print("No test layers are enabled.")
        return 0

    env = os.environ.copy()
    if TEST_USERNAME is not None:
        env["E2E_USERNAME"] = TEST_USERNAME
    if TEST_PASSWORD is not None:
        env["E2E_PASSWORD"] = TEST_PASSWORD
    env.setdefault("SE_TIMEOUT", "30")

    stages: list[tuple[str, int, float]] = []
    report_file = ROOT / REPORT_DIR / "browser-results.xml"

    # 1. Fast JavaScript unit tests (no Selenium or Prism required).
    if RUN_UNIT_TESTS:
        command = [
            NODE_EXECUTABLE, "--test",
            "tests_js/unit/api.test.cjs",
            "tests_js/unit/contract.test.cjs",
        ]
        code, elapsed = run_stage("1/3  JavaScript unit tests", command, env)
        stages.append(("Unit", code, elapsed))
        if code != 0 and STOP_AFTER_FAILED_STAGE:
            return finish(stages, None)

    # 2 and 3. A SINGLE pytest invocation to preserve one Chrome window.
    # Explicit path ordering makes integration tests run before E2E tests.
    browser_paths = []
    if RUN_INTEGRATION_TESTS:
        browser_paths.append("tests/integration")
    if RUN_E2E_TESTS:
        browser_paths.extend(
            str(p.relative_to(ROOT)) for p in sorted((ROOT / "tests").glob("test_*.py"))
        )
        if len(browser_paths) == (1 if RUN_INTEGRATION_TESTS else 0):
            print("No E2E test_*.py files found.", file=sys.stderr)
            stages.append(("Browser", 2, 0.0))
            return finish(stages, None)

    if browser_paths:
        command = [PYTHON_EXECUTABLE, "-m", "pytest", "-v", "-ra", *browser_paths,
                   f"--backend={BACKEND}", f"--api-url={API_URL}",
                   f"--timeout={UI_TIMEOUT_SECONDS}"]
        if FRONTEND_URL:
            command.append(f"--frontend-url={FRONTEND_URL}")
        if CHROME_BINARY:
            command.append(f"--chrome-binary={Path(CHROME_BINARY).expanduser()}")
        if CHROMEDRIVER_PATH:
            command.append(f"--chromedriver-path={Path(CHROMEDRIVER_PATH).expanduser()}")
        if SHOW_BROWSER:
            command.append("--headed")
        if TRACE_BROWSER_SETUP:
            command.extend(["-s", "--trace-e2e"])
        if STOP_ON_FIRST_TEST_FAILURE:
            command.append("-x")
        if ALLOW_CART_MUTATIONS:
            command.append("--allow-mutations")
        if ALLOW_ACCOUNT_CHANGES:
            command.append("--allow-account-changes")
        if ALLOW_ACCOUNT_DELETION:
            command.append("--allow-account-deletion")
        if WRITE_JUNIT_REPORT:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.unlink(missing_ok=True)
            command.append(f"--junitxml={report_file}")

        label = "2/3  Integration + 3/3  E2E (shared Chrome)" if (
            RUN_INTEGRATION_TESTS and RUN_E2E_TESTS
        ) else ("2/3  Integration" if RUN_INTEGRATION_TESTS else "3/3  E2E")
        code, elapsed = run_stage(label, command, env)
        stages.append(("Browser", code, elapsed))
        return finish(stages, report_file if WRITE_JUNIT_REPORT else None)

    return finish(stages, None)


def finish(stages: list[tuple[str, int, float]], report: Path | None) -> int:
    print(f"\n{'=' * 70}\nFINAL SUMMARY\n{'=' * 70}")
    for name, code, elapsed in stages:
        print(f"{name:<14} {'PASS' if code == 0 else 'FAIL':<6} {elapsed:6.1f}s")
    if report and report.is_file():
        counts = junit_counts(report)
        for layer in ("Integration", "E2E"):
            if layer == "Integration" and not RUN_INTEGRATION_TESTS:
                continue
            if layer == "E2E" and not RUN_E2E_TESTS:
                continue
            data = counts[layer]
            print(f"  {layer:<12} {data['passed']} passed, "
                  f"{data['failed']} failed, {data['skipped']} skipped")
        print(f"JUnit report: {report}")
    ok = all(code == 0 for _, code, _ in stages)
    print("RESULT: " + ("ALL SELECTED STAGES PASSED" if ok else "SOME STAGES FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        raise SystemExit(130)
