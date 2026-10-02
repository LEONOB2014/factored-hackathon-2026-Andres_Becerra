"""scripts/build_notebook.py: `# %%` percent source → .ipynb (→ executed → HTML)."""

import nbformat
import pytest

import build_notebook

SOURCE = """\
import os  # ignored: before the first cell marker

# %% [markdown]
# # 99 · Title
# Some *markdown*
#
#no-space prefix is stripped too

# %%
x = 1 + 1

# %%

# %% [markdown]
# ## Second

# %%
print(x * 21)
"""


def test_parse_splits_markdown_and_code_cells():
    cells = build_notebook.parse(SOURCE)
    assert [c.cell_type for c in cells] == ["markdown", "code", "markdown", "code"]


def test_parse_strips_comment_prefixes_from_markdown():
    md = build_notebook.parse(SOURCE)[0].source
    assert md == "# 99 · Title\nSome *markdown*\n\nno-space prefix is stripped too"


def test_parse_drops_empty_code_cells_and_preamble():
    code = [c.source for c in build_notebook.parse(SOURCE) if c.cell_type == "code"]
    assert code == ["x = 1 + 1", "print(x * 21)"]


def test_parse_of_text_without_markers_is_empty():
    assert build_notebook.parse("print('no cells')\n") == []


def test_build_writes_ipynb_next_to_source(tmp_path):
    src = tmp_path / "99_demo.py"
    src.write_text(SOURCE)
    out = build_notebook.build(src, html_dir=None)
    assert out == src.with_suffix(".ipynb")
    nb = nbformat.read(out, as_version=4)
    nbformat.validate(nb)
    assert nb.metadata.kernelspec.name == "python3"
    assert len(nb.cells) == 4


@pytest.mark.slow
def test_build_executes_and_exports_html(tmp_path):
    src = tmp_path / "99_demo.py"
    src.write_text(SOURCE)
    html_dir = tmp_path / "html"
    out = build_notebook.build(src, execute=True, html_dir=html_dir)
    outputs = nbformat.read(out, as_version=4).cells[-1].outputs
    assert outputs[0].text.strip() == "42"
    assert (html_dir / "99_demo.html").read_text().count("42") >= 1
