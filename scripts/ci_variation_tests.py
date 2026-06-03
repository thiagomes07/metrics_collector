#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        msg = "extra test count cannot be negative"
        raise argparse.ArgumentTypeError(msg)
    return value


def non_negative_float(raw: str) -> float:
    value = float(raw)
    if value < 0:
        msg = "slow test delay cannot be negative"
        raise argparse.ArgumentTypeError(msg)
    return value


def build_source(extra_cases: int, slow_seconds: float, fail_mode: str) -> str:
    failure_block = ""
    if fail_mode == "generated-assertion":
        failure_block = """

def test_ci_variation_requested_failure():
    assert humanize.intword(10**6) == "one million"
"""

    return f'''from __future__ import annotations

import time

import pytest

import humanize


@pytest.mark.parametrize(
    "value, expected",
    [
        (1536, "1.5 kB"),
        (10**6, "1.0 MB"),
        (10**9, "1.0 GB"),
    ],
)
def test_generated_naturalsize_cases(value, expected):
    assert humanize.naturalsize(value) == expected


@pytest.mark.parametrize("index", range({extra_cases}))
def test_generated_intcomma_scale(index):
    value = index * 1000 + 1042
    assert "," in humanize.intcomma(value)


def test_ci_variation_slow_path():
    delay = {slow_seconds!r}
    if delay:
        time.sleep(delay)
    assert humanize.precisedelta(3661) == "1 hour, 1 minute and 1 second"
{failure_block}
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra-cases", type=non_negative_int, default=0)
    parser.add_argument("--slow-seconds", type=non_negative_float, default=0.0)
    parser.add_argument(
        "--fail-mode",
        choices=["none", "generated-assertion"],
        default="none",
    )
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        build_source(args.extra_cases, args.slow_seconds, args.fail_mode),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
