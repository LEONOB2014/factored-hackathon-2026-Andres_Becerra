"""Static checks on the notebook series (no kernel, no data).

The `.py` percent files are the source of truth; these tests keep the series
well-formed and the tables it writes in step with what is committed.
"""

import ast
import re

import nbformat
import pytest

import build_notebook
from conftest import NOTEBOOKS, TABLES

SOURCES = sorted(NOTEBOOKS.glob("[0-9][0-9]_*.py"))
WRITES = re.compile(r'to_csv\(OUT / "([\w.]+\.csv)"')
READS = re.compile(r'read_csv\((?:OUT|T) / "([\w.]+\.csv)"')
SCRIPTS = NOTEBOOKS.parent / "scripts"
SCRIPT_WRITES = re.compile(r'to_csv\(\s*OUT / "([\w.]+\.csv)"')


def number(path):
    return int(path.name[:2])


def test_series_is_numbered_01_to_11_without_gaps():
    assert [number(p) for p in SOURCES] == list(range(1, 12))


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_starts_with_a_numbered_title(src):
    first = build_notebook.parse(src.read_text())[0]
    assert first.cell_type == "markdown"
    assert first.source.startswith(f"# {src.name[:2]} · ")


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_code_cells_are_valid_python(src):
    for cell in build_notebook.parse(src.read_text()):
        if cell.cell_type == "code":
            ast.parse(cell.source)


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_imports_shared_code_from_src(src):
    text = src.read_text()
    if "latam_eda" not in text:
        return
    assert 'sys.path.insert(0, "../src")' in text
    assert text.index('sys.path.insert(0, "../src")') < text.index("from latam_eda")


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_no_machine_specific_paths(src):
    assert not re.search(r"/Users/|/home/|[A-Z]:\\\\", src.read_text())


# Scoped series write one table per (dataset, scope): `OUT / f"{PREFIX}_{COUNTRY.lower()}_<kind>.csv"`, resolved
# with the `PREFIX = "..."` and `COUNTRY = "XX"` constants of each generated notebook
# (see scripts/build_country_notebooks.py).
COUNTRY_WRITES = re.compile(r'to_csv\(\s*OUT / f"\{PREFIX\}_\{COUNTRY\.lower\(\)\}_(\w+)\.csv"')
COUNTRY_CONST = re.compile(r'^COUNTRY = "([A-Z]{2,3})"$', re.M)
PREFIX_CONST = re.compile(r'^PREFIX = "(\w+)"$', re.M)


def producers():
    out = {}
    for src in SOURCES + SUB_SOURCES:
        text = src.read_text()
        for table in WRITES.findall(text):
            out.setdefault(table, []).append(src.name)
        code, prefix = COUNTRY_CONST.search(text), PREFIX_CONST.search(text)
        for kind in COUNTRY_WRITES.findall(text) if code and prefix else []:
            out.setdefault(f"{prefix.group(1)}_{code.group(1).lower()}_{kind}.csv", []).append(
                f"{src.parent.name}/{src.name}"
            )
    return out


def script_producers():
    """Tables written by scripts (e.g. warehouse_validation.py) rather than notebooks."""
    out = {}
    for src in sorted(SCRIPTS.glob("*.py")):
        text = src.read_text()
        if "to_csv(" in text:
            for table in sorted(set(SCRIPT_WRITES.findall(text))):
                out.setdefault(table, []).append(src.name)
    return out


def test_every_written_table_is_committed():
    committed = {p.name for p in TABLES.glob("*.csv")}
    assert set(producers()) <= committed


def test_every_committed_table_has_exactly_one_producer():
    made = producers()
    for table, scripts in script_producers().items():
        made.setdefault(table, []).extend(scripts)
    for path in TABLES.glob("*.csv"):
        assert len(made.get(path.name, [])) == 1, (path.name, made.get(path.name))


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_tables_are_read_only_after_they_are_written(src):
    made = producers()
    for table in READS.findall(src.read_text()):
        assert table in made, f"{src.name} reads {table}, which no notebook writes"
        writer = made[table][0]
        assert int(writer[:2]) < number(src), f"{src.name} reads {table} before {writer}"


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.stem)
def test_executed_notebook_matches_its_source(src):
    ipynb = src.with_suffix(".ipynb")
    if not ipynb.exists():
        pytest.skip("executed notebook not present")
    built = build_notebook.parse(src.read_text())
    nb = nbformat.read(ipynb, as_version=4)
    assert [c.cell_type for c in nb.cells] == [c.cell_type for c in built]
    for cell, ref in zip(nb.cells, built, strict=True):
        if cell.cell_type == "markdown":
            assert cell.source == ref.source


# Sub-series live one folder deeper and reach the shared code through ../../src:
#   medallion/   the re-analysis layer by layer (raw -> bronze -> silver -> gold)
#   model_risk/  schema forensics, keys, drift MRM, segmentation and text
SUBSERIES = {
    name: sorted((NOTEBOOKS / name).glob("[0-9][0-9]_*.py"))
    for name in (
        "medallion",
        "model_risk",
        "pipeline",
        "country_all",
        "country_mx",
        "country_co",
        "country_ar",
        "country_compare",
        "backup_all",
        "backup_mx",
        "backup_co",
        "backup_ar",
        "dataset_compare",
        "granularity",
        "granularity_time",
    )
}
SUB_SOURCES = [p for paths in SUBSERIES.values() for p in paths]


@pytest.mark.parametrize("series", SUBSERIES)
def test_sub_series_is_numbered_from_01_without_gaps(series):
    paths = SUBSERIES[series]
    assert paths, f"{series}/ has no notebooks"
    assert [number(p) for p in paths] == list(range(1, len(paths) + 1))


@pytest.mark.parametrize("src", SUB_SOURCES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_sub_series_notebook_is_well_formed(src):
    text = src.read_text()
    cells = build_notebook.parse(text)
    assert cells[0].cell_type == "markdown"
    assert cells[0].source.startswith(f"# {src.name[:2]} · ")
    for cell in cells:
        if cell.cell_type == "code":
            ast.parse(cell.source)
    assert text.index('sys.path.insert(0, "../../src")') < text.index("from latam_eda")
    assert not re.search(r"/Users/|/home/|[A-Z]:\\\\", text)


@pytest.mark.parametrize("src", SUB_SOURCES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_sub_series_executed_notebook_matches_its_source(src):
    test_executed_notebook_matches_its_source(src)
