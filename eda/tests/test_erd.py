"""The ERD and the table catalogues must agree with the official data dictionary PDF."""

import pytest

import compare_backup
import eda_overview
import generate_erd
from conftest import REPO
from latam_eda import data


@pytest.fixture(scope="module")
def dictionary():
    return generate_erd.parse_dictionary()


@pytest.fixture(scope="module")
def tables(dictionary):
    return dictionary[0]


@pytest.fixture(scope="module")
def fks(dictionary):
    return dictionary[1]


def primary_keys(table):
    return [c[0] for c in table["cols"] if "PK" in c[3]]


def test_dictionary_documents_13_tables_and_24_foreign_keys(tables, fks):
    assert len(tables) == 13
    assert len(fks) == 24
    assert sum(len(t["cols"]) for t in tables.values()) == 260


def test_table_kinds(tables):
    kinds = {name: t["kind"] for name, t in tables.items()}
    assert {n for n, k in kinds.items() if k == "FACT"} == set(data.FACTS)
    assert {n for n, k in kinds.items() if k != "FACT"} == set(data.DIMS)


def test_foreign_keys_point_at_documented_columns(tables, fks):
    for child, col, parent, pk in fks:
        assert col in {c[0] for c in tables[child]["cols"]}, f"{child}.{col}"
        assert pk in primary_keys(tables[parent]), f"{parent}.{pk}"


def test_primary_keys_match_the_shared_catalogue(tables):
    for name, table in tables.items():
        keys = primary_keys(table)
        if name == "daily_exchange_rates":
            assert keys == ["date", "source_currency", "target_currency"]
        else:
            assert keys == [data.PK[name]], name


def test_overview_foreign_keys_are_documented(fks):
    assert set(eda_overview.FKS) <= set(fks)


def test_overview_catalogue_matches_shared_catalogue():
    assert list(eda_overview.FACTS) == data.FACTS
    assert list(eda_overview.DIMS) == data.DIMS
    for name, (pk, _) in {**eda_overview.FACTS, **eda_overview.DIMS}.items():
        assert pk == data.PK.get(name), name


def test_backup_comparison_keys_match_shared_catalogue():
    assert {t: data.PK[t] for t in compare_backup.PK} == compare_backup.PK


def test_mermaid_types_have_no_parentheses():
    assert generate_erd.mermaid_type("DECIMAL(18,2)") == "decimal"
    assert generate_erd.mermaid_type("VARCHAR") == "varchar"


def test_committed_erd_is_up_to_date(tables, fks):
    committed = (REPO / "docs" / "dataset" / "erd.md").read_text()
    assert committed == generate_erd.render(tables, fks), (
        "docs/dataset/erd.md is stale: run `uv run scripts/generate_erd.py` in eda/"
    )


def test_erd_declares_every_table_and_relationship(tables, fks):
    mermaid = generate_erd.build_mermaid(tables, fks)
    assert mermaid.startswith("erDiagram")
    for name in tables:
        assert f"    {name} {{" in mermaid
    for child, _, parent, _ in fks:
        assert parent in mermaid and child in mermaid
