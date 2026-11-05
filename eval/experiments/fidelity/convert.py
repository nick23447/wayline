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
  write_outputs      template.yml, instance.json, prediction.json, config.json

convert() runs that pipeline for one instance and one Config. generate.py is
where you list the conversions you want. Nothing here touches the cluster.

Execution model (see README): machine = C cores, 1 core per task.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import itertools
import re

import yaml
from saga import Network, TaskGraph, Schedule
from saga.schedulers import HeftScheduler, CpopScheduler

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

schedule_selector = {
    "heft": HeftScheduler,
    "cpop": CpopScheduler,
}


@dataclass(frozen=True)
class Config:
    """Settings for one conversion. Saved as config.json with each output."""
    scheduler: str = "heft"
    C: int = 8                  # cores per machine
    mode: str = "sleep"         # "sleep" or "cpu"
    # sleep mode: chosen (emulated). cpu mode: measured, machine rate / hash_rate.
    speed: dict[str, float] = field(default_factory=lambda: {m: 1.0 for m in MACHINES})
    sec_per_cost: float = 1.0
    bytes_per_size: float = 1.0
    hash_rate: float = 0.0      # cpu mode: hashes/s of the reference machine (speed 1.0)
    memory: str | None = None   # e.g. "2Gi" for every task; None = calculated per task

    def __post_init__(self):
        if self.mode not in ("sleep", "cpu"):
            raise ValueError(f"Unknown mode {self.mode!r}: use sleep or cpu")
        if self.mode == "cpu" and self.hash_rate <= 0:
            raise ValueError("cpu mode needs hash_rate > 0, or tasks do no work")
        if set(self.speed) != set(MACHINES):
            raise ValueError(f"speed must cover exactly {MACHINES}, got {sorted(self.speed)}")
        if min(self.speed.values()) <= 0:
            raise ValueError(f"speeds must be > 0, got {self.speed}")

    def run_name(self) -> str:
        """Readable settings plus a hash of all of them, so that two Configs
        differing only in speed or scaling never share a template name."""
        digest = hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
        return f"{self.scheduler}-c{self.C}-{self.mode}-{digest[:6]}"


def load_instance(path: Path) -> dict:
    """Read graphs/*.json. Validate: every edge endpoint is a task."""

    with open(path, "r") as f:
        inst = json.load(f)

    tasks = set(inst["tasks"])

    for src, dst, _ in inst["edges"]:
        if src not in tasks:
            raise ValueError(f"Edge source {src} is not a task")
        if dst not in tasks:
            raise ValueError(f"Edge destination {dst} is not a task")
    return inst


def to_task_graph(inst: dict, sec_per_cost: float, bytes_per_size: float) -> TaskGraph:
    """Build saga.TaskGraph with cost in seconds and edge size in bytes.

    Hint: TaskGraph.create(tasks=[(name, cost)], dependencies=[(src, dst, size)])
    (eval/policies/analyze-e2.py uses exactly this call).
    """

    task_graph = TaskGraph.create(
        tasks=[(name, cost * sec_per_cost) for name, cost in inst["tasks"].items()],
        dependencies=[(src, dst, size * bytes_per_size) for src, dst, size in inst["edges"]]
    )
    return task_graph

def build_network(C: int, speed: dict[str, float]) -> Network:
    """saga.Network with C core-nodes per machine: "<machine>-c<i>".

    - node speed  = speed[machine] (emulated; 1.0 = baseline)
    - same machine, different core: LOCAL_BW
    - across machines: BANDWIDTH; SAGA links are undirected, so use
      min(both directions) (what saga-sidecar/bridge.py does)
    - every pair needs an edge, including self-loops (LOCAL_BW)

    Hint: Network.create(nodes=[(name, speed)], edges=[(u, v, bw)])
    """

    core_nodes = []
    node_names = []
    for machine in speed:
        for i in range(C):
            core_nodes.append((f"{machine}-c{i}", speed[machine]))
            node_names.append(f"{machine}-c{i}")

    edges = []
    for u, v in itertools.combinations_with_replacement(node_names, 2):
        if machine_of(u) == machine_of(v):
            edges.append((u, v, LOCAL_BW))
        else:
            edges.append((u, v, min(BANDWIDTH.values())))

    network_graph = Network.create(
        nodes=core_nodes,
        edges=edges
    )
    return network_graph


def run_scheduler(name: str, network, task_graph) -> Schedule:
    """Run a SAGA scheduler by name ("heft", "cpop", ...); return Schedule.

    The Schedule holds each task's node, start and end: that is SAGA's
    prediction. Keep it; do not use Wayline's status.predictedTasks.
    """
    if name not in schedule_selector:
        raise ValueError(f"Unknown scheduler {name}")
    
    scheduler_class = schedule_selector[name]
    schedule = scheduler_class().schedule(network, task_graph)
    return schedule


def machine_of(core_node: str) -> str:
    """"cse-lambda1-c3" -> "cse-lambda1"."""
    return core_node.rsplit("-c", 1)[0]


def real_tasks(schedule: Schedule) -> list:
    """Every scheduled task except SAGA's fake source/sink (Wayline has no such pods)."""
    return [
        task
        for tasks in schedule.mapping.values()
        for task in tasks
        if not task.name.startswith("__super_")
    ]


def node_order(schedule: Schedule) -> dict[str, list[str]]:
    """Merge each machine's cores into one list sorted by predicted start.

    Result feeds schedulerConfig.nodeOrder. Wayline enforces start order per
    machine (enactOrder: order); tasks take any free core.
    """
    by_machine = {}
    for task in real_tasks(schedule):
        by_machine.setdefault(machine_of(task.node), []).append((task.start, task.name))

    ordered_nodes = {
        machine: [name for _, name in sorted(entries)]
        for machine, entries in by_machine.items()
    }

    return ordered_nodes


def check_k8s_name(name: str, max_len: int = 63) -> None:
    """Pods and containers are named after tasks, so names must be DNS labels."""
    if len(name) > max_len or not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name):
        raise ValueError(f"{name!r} is not a valid Kubernetes name (max {max_len} chars)")


def to_template(inst: dict, cfg: Config, order: dict[str, list[str]]) -> str:
    """ODAGTemplate YAML. Per task:

      image, command [python, task.py], dependencies
      resources: {cpu: "1", memory: ...}
      constraints: {nodeNames: [<machine>]}   SAGA's placement (nodeOrder is only order)
      outputs: [{name: "to-<consumer>", dataSize: "<bytes>"}]   one per edge
      inputs:  [{producer: P, object: "to-<this task>"}]         one per in-edge
      runtime / runtimeProfile: per-machine seconds (cost / speed)
      env: FID_MODE, FID_SECONDS, FID_SPEED, FID_HASH_RATE, FID_INPUTS, FID_OUTPUTS

    spec-level: scheduler random (constraints decide the machine; "heft" here
    would mean Wayline's own HEFT), schedulerConfig {nodeOrder, enactOrder: order},
    profiling disabled (we profile ourselves), metadata labels recording C,
    mode, scheduler, scaling (so every run is traceable).

    Built from inst, not the TaskGraph, which may hold SAGA's __super_* tasks.
    """
    fid_speed = ",".join(f"{m}={s}" for m, s in cfg.speed.items())
    machine_for = {task: machine for machine, tasks in order.items() for task in tasks}

    outputs, inputs = {}, {}
    for src, dst, size in inst["edges"]:
        nbytes = int(size * cfg.bytes_per_size)
        outputs.setdefault(src, []).append((f"to-{dst}", nbytes))
        inputs.setdefault(dst, []).append((src, f"to-{dst}", nbytes))

    tasks = []
    for name, cost in inst["tasks"].items():
        check_k8s_name(name)
        seconds = cost * cfg.sec_per_cost
        task_inputs = inputs.get(name, [])
        task_outputs = outputs.get(name, [])

        memory = cfg.memory
        if memory is None:
            # task.py holds payloads in memory, and the limit is hard (OOM kill).
            # 512 MiB + 2x is a safety margin, not a measurement.
            held = sum(n for *_, n in task_inputs) + sum(n for _, n in task_outputs)
            memory = f"{512 + math.ceil(2 * held / 2**20)}Mi"

        task = {
            "name": name,
            "image": IMAGE,
            "command": ["python", "task.py"],
            "dependencies": [p for p, _, _ in task_inputs],
            "resources": {"cpu": "1", "memory": memory},
            "constraints": {"nodeNames": [machine_for[name]]},
            "runtime": seconds,
            "runtimeProfile": {m: seconds / s for m, s in cfg.speed.items()},
            "env": [
                {"name": "FID_MODE", "value": cfg.mode},
                {"name": "FID_SECONDS", "value": str(seconds)},
                {"name": "FID_SPEED", "value": fid_speed},
                {"name": "FID_HASH_RATE", "value": str(cfg.hash_rate)},
                {"name": "FID_INPUTS", "value": ",".join(f"{p}.{o}" for p, o, _ in task_inputs)},
                {"name": "FID_OUTPUTS", "value": ",".join(f"{o}:{n}" for o, n in task_outputs)},
            ],
        }
        if task_inputs:
            task["inputs"] = [{"producer": p, "object": o} for p, o, _ in task_inputs]
        if task_outputs:
            task["outputs"] = [{"name": o, "dataSize": str(n)} for o, n in task_outputs]
        tasks.append(task)

    # Runs are named <template>-run-xxxxx and that name becomes a label value
    # (max 63), so leave room for the 10-char suffix.
    template_name = f"{inst['name']}-{cfg.run_name()}"
    check_k8s_name(template_name, max_len=53)

    data = {
        "apiVersion": "wl.io/v1",
        "kind": "ODAGTemplate",
        "metadata": {
            "name": template_name,
            "namespace": NAMESPACE,
            "labels": {
                "fidelity/c": str(cfg.C),
                "fidelity/mode": cfg.mode,
                "fidelity/scheduler": cfg.scheduler,
                "fidelity/sec-per-cost": str(cfg.sec_per_cost),
                "fidelity/bytes-per-size": str(cfg.bytes_per_size),
                "fidelity/hash-rate": str(cfg.hash_rate),
            },
            # "=" and "," are not allowed in label values
            "annotations": {"fidelity/speed": fid_speed},
        },
        "spec": {
            "scheduler": "random",
            "schedulerConfig": {"nodeOrder": order, "enactOrder": "order"},
            "profiling": {
                "enabled": False,
                "runtimeSource": "manual",
                "bandwidthSource": "external",
            },
            "retention": {"data": {"policy": "keepLatest", "keepRuns": 1}},
            "tasks": tasks,
        },
    }
    return yaml.safe_dump(data, sort_keys=False)


def write_outputs(out: Path, template_yaml: str, inst: dict, cfg: Config, schedule: Schedule) -> None:
    """Write out/template.yml, out/instance.json (exact input), out/config.json,
    and out/prediction.json (makespan + per-task node/start/end from SAGA), and
    create out/runs/ for the runs."""
    (out / "runs").mkdir(parents=True, exist_ok=True)   # run.py saves each run here

    prediction = {
        "makespan": schedule.makespan,
        "tasks": {
            task.name: {
                "node": task.node,
                "machine": machine_of(task.node),
                "start": task.start,
                "end": task.end,
            }
            for task in sorted(real_tasks(schedule), key=lambda t: (t.start, t.name))
        },
    }

    (out / "template.yml").write_text(template_yaml)
    (out / "instance.json").write_text(json.dumps(inst, indent=2) + "\n")
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    (out / "prediction.json").write_text(json.dumps(prediction, indent=2) + "\n")


def convert(instance: Path, cfg: Config, out_root: Path) -> Path:
    """One instance + one Config -> <out_root>/<graph name>/<run name>/.

    Returns that folder. Its template and prediction come from one schedule, so
    keep them together.
    """
    inst = load_instance(instance)
    network = build_network(cfg.C, cfg.speed)
    task_graph = to_task_graph(inst, cfg.sec_per_cost, cfg.bytes_per_size)
    schedule = run_scheduler(cfg.scheduler, network, task_graph)
    template_yaml = to_template(inst, cfg, node_order(schedule))

    out = out_root / inst["name"] / cfg.run_name()
    write_outputs(out, template_yaml, inst, cfg, schedule)
    print(f"wrote {out}")
    return out
