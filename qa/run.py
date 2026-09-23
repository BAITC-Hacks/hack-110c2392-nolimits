"""Run from any directory: python qa/run.py [-k expression]. Never uses a live API."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def main():
    reports = ROOT / "qa" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    xml = reports / f"{stamp}.xml"
    metadata = {
        "timestamp_utc": stamp, "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "working_tree": git("status", "--short"), "python": platform.python_version(),
        "platform": platform.platform(),
    }
    command = [sys.executable, "-m", "pytest", "qa", "backend/tests", "-q", "--tb=short",
               f"--junitxml={xml}", *sys.argv[1:]]
    result = subprocess.run(command, cwd=ROOT)
    cases = []
    if xml.exists():
        for case in ET.parse(xml).iter("testcase"):
            failure, error, skipped = case.find("failure"), case.find("error"), case.find("skipped")
            problem = failure if failure is not None else error
            status = "failed" if problem is not None else "skipped" if skipped is not None else "passed"
            cases.append({"test": case.get("classname", "") + "::" + case.get("name", ""),
                          "status": status, "message": problem.get("message", "") if problem is not None else ""})
    metadata.update({"exit_code": result.returncode, "cases": cases})
    json_path = reports / f"{stamp}.json"
    json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {status: sum(c["status"] == status for c in cases) for status in ["passed", "failed", "skipped"]}
    lines = ["# QA run", "", f"Commit: `{metadata['commit']}`", f"UTC: `{stamp}`",
             f"Python: {metadata['python']}; exit code: {result.returncode}",
             f"Passed: {counts['passed']}; failed: {counts['failed']}; skipped: {counts['skipped']}", "",
             "A failed case is evidence for investigation, not necessarily a distinct defect.", "",
             "| Test | Result |", "| --- | --- |"]
    lines.extend(f"| `{c['test'].replace('|', '/').replace(chr(10), ' ')}` | {c['status']} |" for c in cases)
    report = reports / f"{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReports: {report}\nDetails: {json_path}\nJUnit: {xml}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
