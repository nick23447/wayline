#!/usr/bin/env python3
"""Wayline run -> actual.json + Gantt chart, next to SAGA's prediction.

Input: a run's saved status (kubectl get odag <run> -n wl-runs -o json), stored
as out/<graph>/<run name>/runs/<odag name>/status.json. Writes in that folder:

  actual.json   mirrors prediction.json, from Wayline's measured times
  gantt.png     SAGA's predicted schedule above Wayline's actual one

Usage: python analyze.py out/<graph>/<run name>/runs/<odag name>/status.json [...]

Times come from the SDK (taskStartTime / taskCloseTime, sub-millisecond), and
time 0 is the first task's start, to match SAGA's time 0. status.makespan is not
used: it is whole seconds and starts at the first pod.
"""
from datetime import datetime
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")   # write image files; no window
import matplotlib.pyplot as plt

from saga import ScheduledTask
from saga.utils.draw import draw_gantt


def parse_time(s: str) -> float:
    """RFC 3339 ("2026-11-05T06:38:58.09465146Z") -> Unix seconds."""
    return datetime.fromisoformat(s).timestamp()


def actual_from_status(status: dict) -> dict:
    """Wayline's measured schedule, in the same shape as prediction.json.

    Wayline only knows which machine ran a task, not which core, so "node" is
    the machine here (in prediction.json it is SAGA's core).
    """
    if status["status"].get("phase") != "Succeeded":
        raise ValueError(f"{status['metadata']['name']} did not succeed")
    tasks = status["status"]["tasks"]
    missing = [t["name"] for t in tasks if "taskStartTime" not in t or "taskCloseTime" not in t]
    if missing:
        raise ValueError(f"no SDK timestamps for tasks {missing}")

    starts = {t["name"]: parse_time(t["taskStartTime"]) for t in tasks}
    closes = {t["name"]: parse_time(t["taskCloseTime"]) for t in tasks}
    t0 = min(starts.values())
    first = min(tasks, key=lambda t: starts[t["name"]])

    return {
        "run": status["metadata"]["name"],
        "makespan": max(closes.values()) - t0,
        "makespan_from_odag_start": max(closes.values()) - parse_time(status["status"]["startTime"]),
        "t0": first["taskStartTime"],
        "tasks": {
            t["name"]: {
                "node": t["node"],
                "machine": t["node"],
                "start": starts[t["name"]] - t0,
                "end": closes[t["name"]] - t0,
                "input_read": t.get("inputReadSeconds"),
                "compute": t.get("computeSeconds"),
                "handoff": t.get("handoffSeconds"),
            }
            for t in sorted(tasks, key=lambda t: (starts[t["name"]], t["name"]))
        },
    }


def lanes(tasks: dict, by_core: bool) -> dict[str, list[ScheduledTask]]:
    """Group tasks into Gantt rows, each sorted by start.

    SAGA's tasks go on their core. Wayline's go on numbered slots of their
    machine: a task takes the first slot that is free, so overlapping tasks get
    their own rows. A slot is not the real core (Linux picks that).
    """
    rows: dict[str, list[ScheduledTask]] = {}
    for name, t in sorted(tasks.items(), key=lambda kv: (kv[1]["start"], kv[0])):
        if by_core:
            row = t["node"]
        else:
            i = 0
            while rows.get(f"{t['machine']} slot {i}") and rows[f"{t['machine']} slot {i}"][-1].end > t["start"]:
                i += 1
            row = f"{t['machine']} slot {i}"
        rows.setdefault(row, []).append(ScheduledTask(node=row, name=name, start=t["start"], end=t["end"]))
    return rows


def draw(prediction: dict, actual: dict, scheduler: str, path: Path) -> None:
    """SAGA's Gantt chart above Wayline's, on one time axis."""
    predicted_rows = lanes(prediction["tasks"], by_core=True)
    actual_rows = lanes(actual["tasks"], by_core=False)
    xmax = max(prediction["makespan"], actual["makespan"]) * 1.05

    heights = [max(len(predicted_rows), 1), max(len(actual_rows), 1)]
    fig, (top, bottom) = plt.subplots(
        2, 1, sharex=True, figsize=(10, 1.6 + 0.6 * sum(heights)),
        gridspec_kw={"height_ratios": heights},
    )
    for axis, rows, title, ylabel, makespan in (
        (top, predicted_rows, f"SAGA prediction ({scheduler})", "SAGA core", prediction["makespan"]),
        (bottom, actual_rows, f"Wayline run {actual['run'].rsplit('-', 1)[-1]}", "Wayline slot", actual["makespan"]),
    ):
        draw_gantt(rows, axis=axis, xmax=xmax, font_size=11, tick_font_size=10)
        axis.axvline(makespan, color="#52514e", linestyle="--", linewidth=1)
        axis.set_title(f"{title}: makespan {makespan:.3f} s", fontsize=12, loc="left")
        axis.set_ylabel(ylabel, fontsize=11)
        axis.set_xlabel("")
    bottom.set_xlabel("Seconds from the first task's start", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def analyze(status_path: Path) -> None:
    run_dir = status_path.parent
    template_dir = run_dir.parent.parent   # out/<graph>/<run name>/
    prediction = json.loads((template_dir / "prediction.json").read_text())
    scheduler = json.loads((template_dir / "config.json").read_text())["scheduler"]

    actual = actual_from_status(json.loads(status_path.read_text()))
    (run_dir / "actual.json").write_text(json.dumps(actual, indent=2) + "\n")
    draw(prediction, actual, scheduler, run_dir / "gantt.png")
    print(f"wrote {run_dir}/actual.json and gantt.png "
          f"(makespan {actual['makespan']:.3f} s vs. predicted {prediction['makespan']:.3f} s)")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        analyze(Path(arg))
