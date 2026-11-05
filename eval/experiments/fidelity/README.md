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
├── graphs/
│   └── smoke.json     4-task diamond for end-to-end testing
└── out/               generated; one folder per graph and Config:
    └── <graph name>/<run name>/
        ├── template.yml     apply this
        ├── prediction.json  SAGA's makespan + per-task node/start/end
        ├── instance.json    the exact input
        └── config.json      the exact settings
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
python generate.py

# lambda1: build image (repo root), then run
sudo docker build -f eval/experiments/fidelity/task/Dockerfile \
  -t localhost:5000/wl-fidelity-task:latest .
sudo docker push localhost:5000/wl-fidelity-task:latest
kubectl apply -f out/<graph name>/<run name>/template.yml
wayline run <graph name>-<run name> -n wl-runs
```
