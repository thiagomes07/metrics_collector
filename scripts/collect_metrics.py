#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree as ET

MAIN_FIELDS = [
    "run_id",
    "run_attempt",
    "workflow_name",
    "commit_sha",
    "commit_message",
    "status",
    "event",
    "branch",
    "variant",
    "workflow_duration",
    "lead_time_seconds",
    "job_name",
    "job_status",
    "job_duration",
    "python_version",
    "test_count",
    "test_failures",
    "test_time",
    "test_avg_time",
    "artifact_count",
    "timestamp",
    "html_url",
]

STEP_FIELDS = [
    "run_id",
    "commit_sha",
    "job_name",
    "step_number",
    "step_name",
    "step_status",
    "step_conclusion",
    "step_duration",
    "timestamp",
]


def parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def elapsed_seconds(start: str | None, end: str | None) -> float:
    start_dt = parse_instant(start)
    end_dt = parse_instant(end)
    if not start_dt or not end_dt:
        return 0.0
    return round((end_dt - start_dt).total_seconds(), 3)


def first_line(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().splitlines()[0][:160]


def infer_variant(run: dict[str, Any]) -> str:
    candidates = [
        run.get("display_title"),
        run.get("name"),
        first_line((run.get("head_commit") or {}).get("message")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"(baseline|cache-[\w-]+|extra-tests-\d+|slow-test-\ds|forced-failure|sequential-tests|parallel-tests|repeat-baseline)", candidate)
        if match:
            return match.group(1)
    return "unlabeled"


def infer_python_version(job_name: str) -> str:
    match = re.search(r"3\.\d+", job_name)
    return match.group(0) if match else ""


class StripAuthOnCrossHostRedirect(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = parse.urlparse(req.full_url).netloc
        new_host = parse.urlparse(newurl).netloc
        if old_host != new_host:
            for header in ("accept", "authorization", "x-github-api-version"):
                for collection in (redirected.headers, redirected.unredirected_hdrs):
                    for key in list(collection):
                        if key.lower() == header:
                            del collection[key]
        return redirected


def as_int(value: str | None) -> int:
    if value in (None, ""):
        return 0
    return int(float(value))


def as_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def junit_totals(xml_bytes: bytes) -> dict[str, float | int]:
    root = ET.fromstring(xml_bytes)
    if root.tag.endswith("testsuites") and root.attrib.get("tests"):
        tests = as_int(root.attrib.get("tests"))
        failures = as_int(root.attrib.get("failures")) + as_int(root.attrib.get("errors"))
        elapsed = as_float(root.attrib.get("time"))
    elif root.tag.endswith("testsuite"):
        tests = as_int(root.attrib.get("tests"))
        failures = as_int(root.attrib.get("failures")) + as_int(root.attrib.get("errors"))
        elapsed = as_float(root.attrib.get("time"))
    else:
        suites = [node for node in root.iter() if node.tag.endswith("testsuite")]
        tests = sum(as_int(node.attrib.get("tests")) for node in suites)
        failures = sum(
            as_int(node.attrib.get("failures")) + as_int(node.attrib.get("errors"))
            for node in suites
        )
        elapsed = sum(as_float(node.attrib.get("time")) for node in suites)
    return {
        "test_count": tests,
        "test_failures": failures,
        "test_time": round(elapsed, 6),
        "test_avg_time": round(elapsed / tests, 6) if tests else 0.0,
    }


@dataclass
class GitHubClient:
    token: str
    api_url: str = "https://api.github.com"

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("https://"):
            url = path
        else:
            url = f"{self.api_url}{path}"
        if params:
            return f"{url}?{parse.urlencode(params)}"
        return url

    def _request(self, path: str, params: dict[str, Any] | None = None) -> tuple[bytes, Any]:
        url = self._url(path, params)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "metrics-collector-academic-experiment",
        }
        for attempt in range(6):
            req = request.Request(url, headers=headers)
            try:
                opener = request.build_opener(StripAuthOnCrossHostRedirect())
                with opener.open(req, timeout=45) as response:
                    body = response.read()
                    self._respect_rate_limit(response.headers)
                    return body, response.headers
            except error.HTTPError as exc:
                if exc.code in {403, 429}:
                    self._sleep_for_limit(exc.headers, attempt)
                    continue
                if 500 <= exc.code < 600:
                    time.sleep(min(2**attempt, 30))
                    continue
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"GitHub API returned {exc.code} for {url}: {detail}") from exc
            except error.URLError as exc:
                if attempt == 5:
                    raise RuntimeError(f"Could not reach GitHub API at {url}: {exc}") from exc
                time.sleep(min(2**attempt, 30))
        raise RuntimeError(f"GitHub API request failed after retries: {url}")

    def _respect_rate_limit(self, headers: Any) -> None:
        if headers.get("x-ratelimit-remaining") == "0":
            reset_at = int(headers.get("x-ratelimit-reset", "0"))
            wait = max(0, reset_at - int(time.time())) + 2
            if wait:
                time.sleep(wait)

    def _sleep_for_limit(self, headers: Any, attempt: int) -> None:
        retry_after = headers.get("retry-after")
        if retry_after:
            time.sleep(int(retry_after))
            return
        if headers.get("x-ratelimit-remaining") == "0":
            reset_at = int(headers.get("x-ratelimit-reset", "0"))
            time.sleep(max(1, reset_at - int(time.time())) + 2)
            return
        time.sleep(min(2**attempt, 60))

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body, _headers = self._request(path, params)
        return json.loads(body.decode("utf-8"))

    def paginate(self, path: str, params: dict[str, Any] | None = None, key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = self._url(path, params)
        while next_url:
            body, headers = self._request(next_url)
            payload = json.loads(body.decode("utf-8"))
            page_items = payload[key] if key else payload
            items.extend(page_items)
            next_url = parse_next_link(headers.get("link"))
        return items

    def download(self, url: str) -> bytes:
        body, _headers = self._request(url)
        return body


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip().split(";")
        if len(section) == 2 and section[1].strip() == 'rel="next"':
            return section[0].strip()[1:-1]
    return None


def artifact_summaries(
    client: GitHubClient,
    repo: str,
    run_id: int,
    artifacts_dir: Path | None,
) -> dict[str, dict[str, Any]]:
    artifacts = client.paginate(
        f"/repos/{repo}/actions/runs/{run_id}/artifacts",
        {"per_page": 100},
        key="artifacts",
    )
    summaries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.get("expired"):
            continue
        name = artifact["name"]
        blob = client.download(artifact["archive_download_url"])
        if artifacts_dir:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / f"{run_id}-{name}.zip").write_bytes(blob)
        totals = {"test_count": 0, "test_failures": 0, "test_time": 0.0, "test_avg_time": 0.0}
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.namelist():
                lower = member.lower()
                if lower.endswith("summary.json"):
                    with archive.open(member) as handle:
                        payload = json.loads(handle.read().decode("utf-8"))
                    for field in totals:
                        totals[field] = payload.get(field, totals[field])
                elif lower.endswith(".xml") and ("junit" in lower or "pytest" in lower):
                    with archive.open(member) as handle:
                        totals = junit_totals(handle.read())
        summaries[name] = totals
    return summaries


def totals_for_job(job_name: str, summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    empty = {"test_count": 0, "test_failures": 0, "test_time": 0.0, "test_avg_time": 0.0}
    if "test" not in job_name.lower():
        return empty

    python_version = infer_python_version(job_name)
    matching = []
    for artifact_name, totals in summaries.items():
        if not artifact_name.startswith("pytest-results"):
            continue
        if "sequential" in artifact_name and "sequential" not in job_name.lower():
            continue
        if python_version and python_version not in artifact_name:
            continue
        if "sequential" in job_name.lower() and "sequential" not in artifact_name:
            continue
        matching.append(totals)

    aggregate = dict(empty)
    for totals in matching:
        aggregate["test_count"] += int(totals.get("test_count", 0))
        aggregate["test_failures"] += int(totals.get("test_failures", 0))
        aggregate["test_time"] += float(totals.get("test_time", 0.0))
    if aggregate["test_count"]:
        aggregate["test_avg_time"] = round(aggregate["test_time"] / aggregate["test_count"], 6)
    aggregate["test_time"] = round(aggregate["test_time"], 6)
    return aggregate


def workflow_runs(client: GitHubClient, repo: str, workflow: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"per_page": 100}
    if args.branch:
        params["branch"] = args.branch
    if args.event:
        params["event"] = args.event
    runs = client.paginate(
        f"/repos/{repo}/actions/workflows/{parse.quote(workflow, safe='')}/runs",
        params,
        key="workflow_runs",
    )
    if not args.include_in_progress:
        runs = [run for run in runs if run.get("status") == "completed"]
    return runs[: args.limit]


def collect(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = os.environ.get(args.token_env)
    if not token:
        raise RuntimeError(f"set {args.token_env} with a token that can read Actions metadata")
    client = GitHubClient(token=token, api_url=args.api_url)
    main_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []

    for run in workflow_runs(client, args.repo, args.workflow, args):
        run_id = run["id"]
        jobs = client.paginate(
            f"/repos/{args.repo}/actions/runs/{run_id}/jobs",
            {"filter": "latest", "per_page": 100},
            key="jobs",
        )
        artifacts_dir = args.artifacts_dir / str(run_id) if args.artifacts_dir else None
        summaries = artifact_summaries(client, args.repo, run_id, artifacts_dir)
        commit = run.get("head_commit") or {}
        commit_at = parse_instant(commit.get("timestamp"))
        completed_at = parse_instant(run.get("updated_at"))
        lead_time = round((completed_at - commit_at).total_seconds(), 3) if commit_at and completed_at else 0.0
        workflow_duration = elapsed_seconds(run.get("run_started_at"), run.get("updated_at"))
        timestamp = run.get("run_started_at") or run.get("created_at")

        for job in jobs:
            job_name = job.get("name", "")
            test_totals = totals_for_job(job_name, summaries)
            main_rows.append(
                {
                    "run_id": run_id,
                    "run_attempt": run.get("run_attempt", 1),
                    "workflow_name": run.get("name", ""),
                    "commit_sha": run.get("head_sha", ""),
                    "commit_message": first_line(commit.get("message") or run.get("display_title")),
                    "status": run.get("conclusion") or run.get("status"),
                    "event": run.get("event", ""),
                    "branch": run.get("head_branch", ""),
                    "variant": infer_variant(run),
                    "workflow_duration": workflow_duration,
                    "lead_time_seconds": lead_time,
                    "job_name": job_name,
                    "job_status": job.get("conclusion") or job.get("status"),
                    "job_duration": elapsed_seconds(job.get("started_at"), job.get("completed_at")),
                    "python_version": infer_python_version(job_name),
                    "test_count": test_totals["test_count"],
                    "test_failures": test_totals["test_failures"],
                    "test_time": test_totals["test_time"],
                    "test_avg_time": test_totals["test_avg_time"],
                    "artifact_count": len(summaries),
                    "timestamp": timestamp,
                    "html_url": run.get("html_url", ""),
                }
            )
            for step in job.get("steps", []):
                step_rows.append(
                    {
                        "run_id": run_id,
                        "commit_sha": run.get("head_sha", ""),
                        "job_name": job_name,
                        "step_number": step.get("number", ""),
                        "step_name": step.get("name", ""),
                        "step_status": step.get("status", ""),
                        "step_conclusion": step.get("conclusion", ""),
                        "step_duration": elapsed_seconds(step.get("started_at"), step.get("completed_at")),
                        "timestamp": timestamp,
                    }
                )

    return main_rows, step_rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--workflow", default="pipeline-metrics.yml")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--branch")
    parser.add_argument("--event")
    parser.add_argument("--include-in-progress", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("data/pipeline_metrics.csv"))
    parser.add_argument("--steps-out", type=Path, default=Path("data/step_metrics.csv"))
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--api-url", default="https://api.github.com")
    args = parser.parse_args()

    try:
        main_rows, step_rows = collect(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    write_csv(args.out, MAIN_FIELDS, main_rows)
    write_csv(args.steps_out, STEP_FIELDS, step_rows)
    print(f"wrote {len(main_rows)} job rows to {args.out}")
    print(f"wrote {len(step_rows)} step rows to {args.steps_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
