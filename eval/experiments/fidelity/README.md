# Fidelity: how well does SAGA's model predict Wayline?

Plan: `../../../../fidelity-plan/main.tex` (outside the repo).

## Layout

```
fidelity/
├── task/              dummy task image (one image for every task)
│   ├── Dockerfile
│   └── task.py
├── convert.py         SAGA instance -> SAGA schedule + Wayline ODAGTemplate
└── graphs/
    └── smoke.json     4-task diamond for end-to-end testing
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

`convert.py` turns units into seconds and bytes with `--sec-per-cost` and
`--bytes-per-size`.

## Execution model (see plan)

- Each machine = C identical cores; every task uses exactly 1 core.
- SAGA side: each machine becomes C SAGA nodes (`<machine>-c0..c<C-1>`),
  free links between cores of one machine, measured bandwidth across machines.
- Wayline side: `cpu: "1"` per task, `schedulerConfig.nodeOrder` (per machine,
  sorted by SAGA's predicted start), `enactOrder: order`.

## Task env contract (`task/task.py`)

| Var | Example | Meaning |
|---|---|---|
| `FID_MODE` | `sleep` | `sleep` or `cpu` |
| `FID_SECONDS` | `4.0` | runtime at speed 1.0 (already scaled) |
| `FID_SPEED` | `cse-lambda1=1.0,cse-isha=0.5` | emulated speed per node |
| `FID_HASH_RATE` | `2500000` | cpu mode: hashes/s at speed 1.0 (from calibration) |
| `FID_INPUTS` | `a.to-b` | `producer.object`, comma-separated |
| `FID_OUTPUTS` | `to-c:1000000` | `object:bytes`, comma-separated |

## Workflow

```bash
# laptop: schedule + generate
python convert.py graphs/smoke.json --scheduler heft --C 8 --out out/smoke-heft

# lambda1: build image (repo root), then run
sudo docker build -f eval/experiments/fidelity/task/Dockerfile \
  -t localhost:5000/wl-fidelity-task:latest .
sudo docker push localhost:5000/wl-fidelity-task:latest
kubectl apply -f out/smoke-heft/template.yml
wayline run <template-name> -n wl-runs
```
