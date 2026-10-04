"""Opt-in: run each pipeline notebook's cells in-process, then drive every ipywidgets explorer through its options.

    uv run pytest -m notebooks -k pipeline_explorers     # a few minutes once the scratch lakehouse exists

Executing a notebook calls each explorer once, with its default value; a broken option only shows up when someone
picks it. This test executes the cells (figures and displays stubbed), then sets every Dropdown to each of its
options, which fires the registered callbacks, before the last cell closes the database. Outside a kernel an
ipywidgets Output does not swallow exceptions, so a failing callback fails the test.
"""

import ipywidgets as w
import pytest

import build_notebook
from latam_eda import pipeline as pipe
from test_notebook_sources import SUBSERIES

PIPELINE = SUBSERIES["pipeline"]
pytestmark = [pytest.mark.notebooks, pytest.mark.data, pytest.mark.slow]
MAX_OPTIONS = 40  # long dropdowns (every model, every rule) are sampled evenly


def _scratch_ready() -> bool:
    work = pipe.default_workdir(pipe.repo_root())
    return (work / "target" / "manifest.json").exists() and (work / "lakehouse.duckdb").exists()


@pytest.mark.skipif(
    not _scratch_ready(), reason="scratch lakehouse not built: run the pipeline series first"
)
@pytest.mark.parametrize("src", PIPELINE, ids=lambda p: p.stem)
def test_every_explorer_option_runs(src, monkeypatch):
    import plotly.graph_objects as go

    monkeypatch.chdir(src.parent)
    monkeypatch.setattr(go.Figure, "show", lambda self, *a, **k: None)
    cells = [c.source for c in build_notebook.parse(src.read_text()) if c.cell_type == "code"]
    ns: dict = {"__name__": "__main__"}
    for code in cells[:-1]:  # the last cell closes the scratch lakehouse
        exec(compile(code, str(src), "exec"), ns)  # noqa: S102 - runs this repository's own notebook source
    dropdowns = [v for v in ns.values() if isinstance(v, w.Dropdown)]
    for dd in dropdowns:
        options = list(dd.options)
        step = max(1, len(options) // MAX_OPTIONS)
        for opt in options[::step]:
            dd.value = opt[1] if isinstance(opt, tuple) else opt
    exec(compile(cells[-1], str(src), "exec"), ns)  # noqa: S102 - same
