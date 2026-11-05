# Fidelity: how well does SAGA's model predict Wayline?

Plan: `../../../../fidelity-plan/main.tex` (outside the repo).

## Layout

```
fidelity/
├── task/              dummy task image (one image for every task)
│   ├── Dockerfile
│   └── task.py
├── convert.py         one instance + one Config -> SAGA schedule + ODAGTemplate
├── generate.py        edit this: lists the convert() calls you want
├── run.py             runs templates on Wayline and collects each run (lambda1)
├── analyze.py         one run -> actual.json + gantt.png (run.py calls it)
├── graphs/
│   └── smoke.json     4-task diamond for end-to-end testing
└── out/               generated; one folder per graph and Config:
    ├── run-log.csv    one line per run (run.py)
    └── <graph name>/<run name>/
        ├── template.yml     apply this
        ├── prediction.json  SAGA's makespan + per-task node/start/end
        ├── instance.json    the exact input
        ├── config.json      the exact settings
        └── runs/<odag name>/
            ├── status.json  the run as Wayline recorded it
            ├── logs.txt     every task's log
            ├── actual.json  same shape as prediction.json, measured
            └── gantt.png    SAGA's schedule above Wayline's
```

## Instance format (`graphs/*.json`)

```json
{
  "name": "smoke-diamond",
  "source": "hand-written",
  "tasks": {"a": 2.0, "b": 4.0},
  "edges": [["a", "b", 1.0]]
}
```

`tasks`: task -> cost (cost units). `edges`: `[producer, consumer, size]` (size units).

`convert.py` turns units into seconds and bytes with `Config.sec_per_cost` and
`Config.bytes_per_size`.

Task names must be valid Kubernetes names (lowercase letters, digits, hyphens),
since pods and containers are named after them. Graph names must be unique
across datasets, since template names include them but not the output folder.

## Execution model (see plan)

- Each machine = C identical cores; every task uses exactly 1 core.
- SAGA side: each machine becomes C SAGA nodes (`<machine>-c0..c<C-1>`),
  free links between cores of one machine, measured bandwidth across machines.
- Wayline side: `cpu: "1"` and `constraints.nodeNames: [<machine>]` per task,
  `schedulerConfig.nodeOrder` (per machine, sorted by SAGA's predicted start),
  `enactOrder: order`.

## Task env contract (`task/task.py`)

| Var | Example | Meaning |
|---|---|---|
| `FID_MODE` | `sleep` | `sleep` or `cpu` |
| `FID_SECONDS` | `4.0` | runtime at speed 1.0 (already scaled) |
| `FID_SPEED` | `cse-lambda1=1.0,cse-isha=0.5` | speed per node. Sleep mode applies it; cpu mode only logs the planned time from it |
| `FID_HASH_RATE` | `2500000` | cpu mode: hashes/s of the reference machine (from calibration) |
| `FID_INPUTS` | `a.to-b` | `producer.object`, comma-separated |
| `FID_OUTPUTS` | `to-c:1000000` | `object:bytes`, comma-separated |

## Workflow

```bash
# laptop: edit the convert() calls in generate.py, then schedule + generate
PYTHONHASHSEED=0 python generate.py

# lambda1: build image (repo root) when task.py changed
sudo docker build -f eval/experiments/fidelity/task/Dockerfile \
  -t localhost:5000/wl-fidelity-task:latest .
sudo docker push localhost:5000/wl-fidelity-task:latest

# lambda1, from fidelity/ with the venv active: run and collect, one at a time
python run.py out/<graph name>/<run name> [more folders] --reps 20 --shuffle 1
```

For each run, `run.py` applies the template, starts the run, waits for it,
saves `status.json` and `logs.txt`, deletes the run (Wayline does not clean up
when profiling is off), then calls `analyze.py`. It stops if another run is
still active in the namespace. A run that fails or times out is saved and
logged, not analyzed. To analyze a saved run again:
`python analyze.py out/<graph>/<run name>/runs/<odag>/status.json`.

Measured makespan = first task start -> last task close (SDK times), not
Wayline's `status.makespan` (whole seconds, from the first pod).
