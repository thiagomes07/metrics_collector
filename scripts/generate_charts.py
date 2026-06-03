#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def outlier_mask(series: pd.Series) -> pd.Series:
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return pd.Series(False, index=series.index)
    return series > q3 + 1.5 * iqr


def run_frame(df: pd.DataFrame) -> pd.DataFrame:
    numeric = ["workflow_duration", "job_duration", "test_count", "test_failures", "test_time"]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    runs = (
        df.groupby("run_id", as_index=False)
        .agg(
            timestamp=("timestamp", "min"),
            variant=("variant", "first"),
            status=("status", "first"),
            workflow_duration=("workflow_duration", "max"),
            test_count=("test_count", "sum"),
            test_failures=("test_failures", "sum"),
            commit_sha=("commit_sha", "first"),
        )
        .sort_values(["timestamp", "run_id"])
    )
    runs["label"] = range(1, len(runs) + 1)
    return runs


def pipeline_duration_chart(runs: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.8))
    colors = runs["status"].map(lambda status: "#2f855a" if status == "success" else "#c53030")
    ax.bar(runs["label"], runs["workflow_duration"], color=colors)
    ax.set_title("Tempo total do pipeline por execução")
    ax.set_xlabel("Execução")
    ax.set_ylabel("Duração do workflow (s)")
    ax.set_xticks(runs["label"])
    ax.set_xticklabels(runs["variant"], rotation=35, ha="right")
    ax.grid(axis="y", alpha=0.25)
    for _, row in runs[outlier_mask(runs["workflow_duration"])].iterrows():
        ax.annotate(
            "outlier",
            (row["label"], row["workflow_duration"]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def job_duration_chart(df: pd.DataFrame, out: Path) -> None:
    jobs = (
        df.groupby("job_name", as_index=False)["job_duration"]
        .mean()
        .sort_values("job_duration")
    )
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.barh(jobs["job_name"], jobs["job_duration"], color="#2b6cb0")
    ax.set_title("Tempo médio por job")
    ax.set_xlabel("Duração média (s)")
    ax.set_ylabel("Job")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def success_failure_chart(runs: pd.DataFrame, out: Path) -> None:
    counts = runs["status"].value_counts().reindex(["success", "failure"], fill_value=0)
    total = counts.sum()
    labels = [f"{status}\n{count} ({count / total:.0%})" for status, count in counts.items()]
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    ax.bar(labels, counts.values, color=["#2f855a", "#c53030"])
    ax.set_title("Taxa de sucesso e falha")
    ax.set_ylabel("Execuções")
    ax.set_ylim(0, max(counts.max() + 1, 2))
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def tests_vs_duration_chart(runs: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.6))
    colors = runs["status"].map(lambda status: "#2f855a" if status == "success" else "#c53030")
    ax.scatter(runs["test_count"], runs["workflow_duration"], s=80, c=colors, edgecolor="#1a202c")
    ax.set_title("Relação entre quantidade de testes e duração do pipeline")
    ax.set_xlabel("Testes executados")
    ax.set_ylabel("Duração do workflow (s)")
    ax.grid(alpha=0.25)
    for _, row in runs[outlier_mask(runs["workflow_duration"])].iterrows():
        ax.annotate(
            row["variant"],
            (row["test_count"], row["workflow_duration"]),
            xytext=(8, 5),
            textcoords="offset points",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def step_duration_chart(steps_path: Path, out: Path) -> None:
    steps = pd.read_csv(steps_path)
    steps["step_duration"] = pd.to_numeric(steps["step_duration"], errors="coerce").fillna(0)
    slow_steps = (
        steps.groupby("step_name", as_index=False)["step_duration"]
        .mean()
        .sort_values("step_duration")
        .tail(10)
    )
    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.barh(slow_steps["step_name"], slow_steps["step_duration"], color="#805ad5")
    ax.set_title("Etapas mais caras em média")
    ax.set_xlabel("Duração média (s)")
    ax.set_ylabel("Etapa")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, default=Path("data/pipeline_metrics.csv"))
    parser.add_argument("--steps", type=Path, default=Path("data/step_metrics.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("charts"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.metrics)
    runs = run_frame(df)

    pipeline_duration_chart(runs, args.out_dir / "pipeline_duration_by_run.png")
    job_duration_chart(df, args.out_dir / "job_duration_by_job.png")
    success_failure_chart(runs, args.out_dir / "success_failure_rate.png")
    tests_vs_duration_chart(runs, args.out_dir / "tests_vs_duration.png")
    if args.steps.exists():
        step_duration_chart(args.steps, args.out_dir / "step_duration_by_step.png")

    print(f"generated charts in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
