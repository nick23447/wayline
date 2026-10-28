#!/usr/bin/env python3
"""SAGA instance -> SAGA schedule + prediction -> Wayline ODAGTemplate.

Runs on a laptop with public anrg-saga (pip install anrg-saga pyyaml).

Pipeline:
  load_instance      graphs/*.json -> dict
  to_task_graph      dict -> saga.TaskGraph   (costs in seconds, sizes in bytes)
  build_network      machines x C cores -> saga.Network
  run_scheduler      saga scheduler -> saga.Schedule
  node_order         Schedule -> {machine: [task, ...]} by predicted start
  to_template        everything -> ODAGTemplate YAML
  write_outputs      template.yml, instance.json, prediction.json

Execution model (see README): machine = C cores, 1 core per task.
"""
import argparse
import json
from pathlib import Path

# from saga import Network, TaskGraph            # TODO: uncomment when used
# from saga.schedulers import HeftScheduler, CpopScheduler, ...

MACHINES = ["cse-lambda1", "cse-isha"]
IMAGE = "cse-lambda1:5000/wl-fidelity-task:latest"
NAMESPACE = "wl-runs"

# Measured 2026-10-27 (iperf3), bytes/s. Keep in sync with the ConfigMap.
BANDWIDTH = {
    ("cse-lambda1", "cse-isha"): 117_000_000,
    ("cse-isha", "cse-lambda1"): 117_625_000,
}
LOCAL_BW = 1e12   # between cores of one machine: effectively free
                  # (finite on purpose: SAGA divides by it; see bridge.py)


def load_instance(path: Path) -> dict:
    """Read graphs/*.json. Validate: every edge endpoint is a task."""
    # TODO
    raise NotImplementedError


def to_task_graph(inst: dict, sec_per_cost: float, bytes_per_size: float):
    """Build saga.TaskGraph with cost in seconds and edge size in bytes.

    Hint: TaskGraph.create(tasks=[(name, cost)], dependencies=[(src, dst, size)])
    (eval/policies/analyze-e2.py uses exactly this call).
    """
    # TODO
    raise NotImplementedError


def build_network(C: int, speed: dict[str, float]):
    """saga.Network with C core-nodes per machine: "<machine>-c<i>".

    - node speed  = speed[machine] (emulated; 1.0 = baseline)
    - same machine, different core: LOCAL_BW
    - across machines: BANDWIDTH; SAGA links are undirected, so use
      min(both directions) (what saga-sidecar/bridge.py does)
    - every pair needs an edge, including self-loops (LOCAL_BW)

    Hint: Network.create(nodes=[(name, speed)], edges=[(u, v, bw)])
    """
    # TODO
    raise NotImplementedError


def run_scheduler(name: str, network, task_graph):
    """Run a SAGA scheduler by name ("heft", "cpop", ...); return Schedule.

    The Schedule holds each task's node, start and end: that is SAGA's
    prediction. Keep it; do not use Wayline's status.predictedTasks.
    """
    # TODO
    raise NotImplementedError


def machine_of(core_node: str) -> str:
    """"cse-lambda1-c3" -> "cse-lambda1"."""
    # TODO
    raise NotImplementedError


def node_order(schedule) -> dict[str, list[str]]:
    """Merge each machine's cores into one list sorted by predicted start.

    Result feeds schedulerConfig.nodeOrder. Wayline enforces start order per
    machine (enactOrder: order); tasks take any free core.
    """
    # TODO
    raise NotImplementedError


def to_template(inst: dict, args, task_graph, order: dict[str, list[str]]) -> str:
    """ODAGTemplate YAML. Per task:

      image, command [python, task.py], dependencies
      resources: {cpu: "1", memory: ...}
      outputs: [{name: "to-<consumer>", dataSize: "<bytes>"}]   one per edge
      inputs:  [{producer: P, object: "to-<this task>"}]         one per in-edge
      runtime / runtimeProfile: per-machine seconds (cost / speed)
      env: FID_MODE, FID_SECONDS, FID_SPEED, FID_HASH_RATE, FID_INPUTS, FID_OUTPUTS

    spec-level: scheduler, schedulerConfig {nodeOrder, enactOrder: order},
    profiling disabled (we profile ourselves), metadata labels recording C,
    mode, scheduler, scaling (so every run is traceable).

    Hint: eval/experiments/E11/gen_e11.py template() builds the same thing.
    Prefer building a dict and yaml.safe_dump over string formatting.
    """
    # TODO
    raise NotImplementedError


def write_outputs(out: Path, template_yaml: str, inst: dict, schedule) -> None:
    """Write out/template.yml, out/instance.json (exact input), and
    out/prediction.json (makespan + per-task node/start/end from SAGA)."""
    # TODO
    raise NotImplementedError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("instance", type=Path)
    p.add_argument("--scheduler", default="heft")
    p.add_argument("--C", type=int, default=8, help="cores per machine")
    p.add_argument("--mode", choices=["sleep", "cpu"], default="sleep")
    p.add_argument("--speed", default="cse-lambda1=1.0,cse-isha=1.0",
                   help="emulated speed per machine")
    p.add_argument("--sec-per-cost", type=float, default=1.0)
    p.add_argument("--bytes-per-size", type=float, default=1.0)
    p.add_argument("--hash-rate", type=float, default=0.0,
                   help="cpu mode: hashes/s at speed 1.0 (calibration)")
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    # TODO: wire the pipeline in the module docstring together.
    raise NotImplementedError


if __name__ == "__main__":
    main()
