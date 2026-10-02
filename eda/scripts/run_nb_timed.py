#!/usr/bin/env python3
"""Execute a notebook cell by cell, printing per-cell timings (to locate slow/hung cells)."""

import sys
import time

import nbformat
from nbclient import NotebookClient

path = sys.argv[1]
nb = nbformat.read(path, as_version=4)
client = NotebookClient(
    nb,
    timeout=int(sys.argv[2]) if len(sys.argv) > 2 else 900,
    kernel_name="python3",
    resources={"metadata": {"path": str(__import__("pathlib").Path(path).resolve().parent)}},
)
with client.setup_kernel():
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        t = time.time()
        first = cell.source.strip().splitlines()[0][:70] if cell.source.strip() else ""
        try:
            client.execute_cell(cell, i)
            print(f"[{i:3d}] {time.time() - t:7.1f}s  {first}", flush=True)
        except Exception as e:
            print(
                f"[{i:3d}] FAILED after {time.time() - t:.1f}s  {first}\n{str(e)[-600:]}",
                flush=True,
            )
            break
nbformat.write(nb, path)
