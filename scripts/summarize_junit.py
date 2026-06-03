#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET


def as_int(value: str | None) -> int:
    if value in (None, ""):
        return 0
    return int(float(value))


def as_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def junit_totals(path: Path) -> dict[str, float | int]:
    root = ET.parse(path).getroot()
    if root.tag.endswith("testsuites") and root.attrib.get("tests"):
        tests = as_int(root.attrib.get("tests"))
        failures = as_int(root.attrib.get("failures")) + as_int(root.attrib.get("errors"))
        skipped = as_int(root.attrib.get("skipped"))
        elapsed = as_float(root.attrib.get("time"))
    elif root.tag.endswith("testsuite"):
        tests = as_int(root.attrib.get("tests"))
        failures = as_int(root.attrib.get("failures")) + as_int(root.attrib.get("errors"))
        skipped = as_int(root.attrib.get("skipped"))
        elapsed = as_float(root.attrib.get("time"))
    else:
        suites = [node for node in root.iter() if node.tag.endswith("testsuite")]
        tests = sum(as_int(node.attrib.get("tests")) for node in suites)
        failures = sum(
            as_int(node.attrib.get("failures")) + as_int(node.attrib.get("errors"))
            for node in suites
        )
        skipped = sum(as_int(node.attrib.get("skipped")) for node in suites)
        elapsed = sum(as_float(node.attrib.get("time")) for node in suites)

    return {
        "test_count": tests,
        "test_failures": failures,
        "test_skipped": skipped,
        "test_time": round(elapsed, 6),
        "test_avg_time": round(elapsed / tests, 6) if tests else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("junit_xml", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--cache-hit", default="unknown")
    args = parser.parse_args()

    payload = {
        **junit_totals(args.junit_xml),
        "variant": args.variant,
        "python_version": args.python_version,
        "cache_hit": args.cache_hit,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
