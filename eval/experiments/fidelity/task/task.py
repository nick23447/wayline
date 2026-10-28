#!/usr/bin/env python3
"""Fidelity dummy task: read inputs, do work, send named outputs.

One image serves every task; everything task-specific comes from env vars
(see ../README.md). Modes:
  sleep  sleep FID_SECONDS / speed[node]          -> compute is exact
  cpu    hash for FID_SECONDS / speed[node] worth  -> real compute + contention
         of work, using FID_HASH_RATE

Model: eval/experiments/E11/tasks/task.py (same pattern), except payloads
must be RANDOM bytes: the data agent gzips transfers, so zeros are ~free.
"""
import os
import time
import hashlib
import random

from wl import WlTask


def parse_map(s: str, sep: str) -> dict[str, str]:
    """"a=1,b=2" -> {"a": "1", "b": "2"} (sep is "=" or ":"). Empty -> {}."""

    result = {}
    if len(s) == 0:
        return result
   
    for item in s.split(","):
        if not item.strip():
            continue
        key, value = item.split(sep, 1)
        result[key] = value
        
    return result

def node_speed(node: str) -> float:
    """Speed factor for this node from FID_SPEED; default 1.0."""

    speed_factor = float(parse_map(os.environ.get("FID_SPEED", ""), "=").get(node, 1.0))
    if speed_factor <= 0:
        raise ValueError(f"FID_SPEED for {node} must be > 0, got {speed_factor}")
    
    return speed_factor

def read_inputs(task: WlTask) -> int:
    """Read every input in FID_INPUTS; return total bytes read.

    Hint: named inputs are read with task.recv_raw(peer="producer.object").
    Inputs must be read even though we ignore them: reading is part of the
    real cost being measured.
    """
    inputs = os.environ.get("FID_INPUTS", "")
    if not inputs:
        return 0

    total = 0
    for peer in inputs.split(','):
        if not peer.strip():
            continue
        data = task.recv_raw(peer=peer)
        total += len(data)
        del data
    return total

def do_work(mode: str, seconds: float) -> None:
    """Spend `seconds` of work (already divided by the node's speed).

    sleep: time.sleep(seconds)
    cpu:   seconds * FID_HASH_RATE iterations of
           d = hashlib.sha256(d).digest()   (see E11's spin())
    """

    if mode == "sleep":
        time.sleep(seconds)

    elif mode == "cpu":
        hash_rate = os.environ.get("FID_HASH_RATE", "")
        if not hash_rate:
            raise ValueError("FID_HASH_RATE must be set in cpu mode")

        d = b"wl-fidelity"
        for _ in range(int(seconds * float(hash_rate))):
            d = hashlib.sha256(d).digest()

    else:
        raise ValueError(f"Unknown FID_MODE {mode!r}: use sleep or cpu")

def payload(nbytes: int) -> bytes:
    """Random bytes of length nbytes (NOT zeros: the agent gzips).

    Hint: random.randbytes(n) is much faster than os.urandom for large n;
    cryptographic randomness is not needed, only incompressibility.
    """
    return random.randbytes(nbytes)

def send_outputs(task: WlTask) -> None:
    """Send each output in FID_OUTPUTS ("object:bytes,...").

    Hint: named output -> task.send_raw("object", data).
    Leaf task (no outputs): E11 sends task.send_raw(b"done"); do the same.
    """
    output = parse_map(os.environ.get("FID_OUTPUTS", ""), ":")
    if not output:
        task.send_raw(b"done")
        return

    for name, size in output.items():
        data = payload(int(size))
        task.send_raw(name, data)
        del data

def main() -> None:
    task = WlTask()
    node = task.node                 # set from NODE_NAME (downward API)
    mode = os.environ.get("FID_MODE", "sleep")
    base = float(os.environ["FID_SECONDS"])

    in_bytes = read_inputs(task)
    seconds = base / node_speed(node)

    start_time = time.perf_counter()
    do_work(mode, seconds)
    time.sleep(seconds)
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time

    send_outputs(task)
    print(f"[fidelity] task={task.name} node={node} mode={mode} "
      f"planned={seconds:.3f} measured={elapsed:.3f} in_bytes={in_bytes}", flush=True)
    task.close()

if __name__ == "__main__":
    main()
