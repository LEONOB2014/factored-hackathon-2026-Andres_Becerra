#!/usr/bin/env python3
"""Execute a notebook cell by cell, printing per-cell timings (to locate slow/hung cells).

uv run scripts/run_nb_timed.py notebooks/07_anomaly_detection_classical.ipynb [timeout_s]
"""

import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def run(path: Path, timeout: int = 900) -> list[tuple[int, float, bool]]:
    """Run code cells in order, stop at the first failure; save outputs back to `path`.

    Returns (cell index, seconds, succeeded) for every code cell that was attempted.
    """
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(Path(path).resolve().parent)}},
    )
    timings = []
    with client.setup_kernel():
        for i, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue
            t = time.time()
            first = cell.source.strip().splitlines()[0][:70] if cell.source.strip() else ""
            try:
                client.execute_cell(cell, i)
                timings.append((i, time.time() - t, True))
                print(f"[{i:3d}] {time.time() - t:7.1f}s  {first}", flush=True)
            except Exception as e:
                timings.append((i, time.time() - t, False))
                print(
                    f"[{i:3d}] FAILED after {time.time() - t:.1f}s  {first}\n{str(e)[-600:]}",
                    flush=True,
                )
                break
    nbformat.write(nb, path)
    return timings


if __name__ == "__main__":
    run(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 900)
