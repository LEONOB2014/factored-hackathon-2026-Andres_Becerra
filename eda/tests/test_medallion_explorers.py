"""Opt-in: execute each medallion notebook, then drive every ipywidgets explorer it defines.

    uv run pytest -m notebooks -k explorers     # about 6 minutes for 01 on the full data

Executing a notebook never fires widget callbacks, so a broken explorer only shows up when
someone clicks it. This test sets every explorer through its tables, columns and options and
calls its draw function. The explorers' Output widgets are swapped for pass-through sinks,
because an Output widget swallows exceptions raised inside it.
"""

import nbformat
import pytest
from nbclient import NotebookClient

import build_notebook
from test_notebook_sources import SUBSERIES

MEDALLION = SUBSERIES["medallion"]

pytestmark = [pytest.mark.notebooks, pytest.mark.data, pytest.mark.slow]

SINKS = """
class _Sink:
    def __enter__(self): return self
    def __exit__(self, *a): return False      # let exceptions propagate
    def clear_output(self, *a, **k): pass
out_col = out_x = out_g = out_ts = out_sc = out_sl = _Sink()
go.Figure.show = lambda self, *a, **k: None
h = lambda text: None
"""

DRIVE = """
for t in TABLES:
    w_t.value = t
    for c in w_c.options:
        w_c.value = c
        for k in w_k.options:
            w_k.value = k
            for lg in (False, True):
                w_log.value = lg
                _draw_col()
for t in TABLES:
    x_t.value = t
    opts = list(x_r.options)
    for r_ in opts[:4]:
        for c_ in opts[:4]:
            x_r.value, x_c.value = r_, c_
            for nm in x_norm.options:
                x_norm.value = nm
                _draw_x()
for t in TABLES:
    g_t.value = t
    for y in g_y.options:
        g_y.value = y
        for by in list(g_by.options)[:3]:
            g_by.value = by
            for k in g_k.options:
                g_k.value = k
                for lg in (False, True):
                    g_log.value = lg
                    _draw_g()
for t in TIME:
    ts_t.value = t
    for d in ts_d.options:
        ts_d.value = d
        for gr in ts_grain.options:
            ts_grain.value = gr
            for ag in ts_agg.options:
                ts_agg.value = ag
                if ts_v.options:
                    ts_v.value = ts_v.options[0]
                for sp in list(ts_split.options)[:2]:
                    ts_split.value = sp
                    _draw_ts()
for t in TABLES:
    sc_t.value = t
    nums = list(sc_x.options)
    for xx in nums[:3]:
        for yy in nums[:3]:
            sc_x.value, sc_y.value = xx, yy
            for col in list(sc_c.options)[:2]:
                sc_c.value = col
                for lx, ly in ((False, False), (True, True)):
                    sc_lx.value, sc_ly.value = lx, ly
                    _draw_sc()
wheres = {"transactions": ["is_fraud", "currency = 'COP' and amount > 1e6", "no_such_column > 1"]}
for t in TABLES:
    sl_t.value = t
    for wh in wheres.get(t, ["true"]):
        sl_w.value = wh
        for c in sl_c.options:
            sl_c.value = c
            for lg in (False, True):
                sl_log.value = lg
                _draw_sl()
"""


@pytest.mark.parametrize("src", MEDALLION, ids=lambda p: p.stem)
def test_every_explorer_draws_without_error(src):
    nb = nbformat.v4.new_notebook(cells=build_notebook.parse(src.read_text()))
    if "widgets.Dropdown" not in src.read_text():
        pytest.skip("no explorers in this notebook")
    nb.cells += [nbformat.v4.new_code_cell(SINKS), nbformat.v4.new_code_cell(DRIVE)]
    NotebookClient(
        nb,
        timeout=3600,
        kernel_name="python3",
        resources={"metadata": {"path": str(src.parent)}},
    ).execute()
