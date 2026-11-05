#!/usr/bin/env python3
"""Convert datasets to Wayline templates: edit the calls below, then run this.

Each call converts one graph with its own settings (see Config in convert.py).
The last argument is where its output goes, so use subfolders to organize them.
"""
from pathlib import Path

from convert import Config, convert

HERE = Path(__file__).resolve().parent
GRAPHS = HERE / "graphs"
OUT = HERE / "out"

convert(GRAPHS / "smoke.json", Config(scheduler="heft", C=8), OUT)
convert(GRAPHS / "smoke.json", Config(scheduler="cpop", C=8), OUT)

# A whole dataset, all with the same settings:
# for graph in (GRAPHS / "wfcommons").glob("*.json"):
#     convert(graph, Config(scheduler="heft", C=4), OUT / "wfcommons")
