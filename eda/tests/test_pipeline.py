"""The dbt_lakehouse emulator of the pipeline series, on a tiny synthetic manifest (no dataset, no dbt)."""

import json

import pandas as pd
import pytest

from latam_eda import pipeline as pipe

PROJECT = "latam_lakehouse"


def node(kind, name, path, code="", deps=(), mat=None, schema="silver", **config):
    key = f"{kind}.{PROJECT}.{name}"
    return key, {
        "resource_type": kind,
        "name": name,
        "package_name": PROJECT,
        "original_file_path": path,
        "database": "lakehouse",
        "schema": schema,
        "alias": name,
        "relation_name": None if kind == "test" else f'"lakehouse"."{schema}"."{name}"',
        "compiled_code": code,
        "depends_on": {"nodes": list(deps)},
        "config": {"materialized": mat or kind, **config},
        "columns": {},
        "description": f"{name} description",
    }


@pytest.fixture
def project(tmp_path):
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "codes.csv").write_text(
        "code,label,flag,n,x\n00,zero,true,1,1.5\n05,five,false,22,2\n"
    )
    src = tmp_path / "src.parquet"
    pd.DataFrame({"id": ["a", "b", "c"], "v": [1, 2, 3], "code": ["00", "05", "99"]}).to_parquet(
        src
    )
    nodes = dict(
        [
            node("seed", "codes", "seeds/codes.csv", schema="reference"),
            node(
                "model",
                "stg_x",
                "models/silver/staging/stg_x.sql",
                mat="view",
                code=f"select * from read_parquet('{src}')",
            ),
            node(
                "model",
                "int_x",
                "models/silver/conformed/int_x.sql",
                mat="table",
                code='select s.*, c.label from "lakehouse"."silver"."stg_x" s '
                'left join "lakehouse"."reference"."codes" c using (code)',
                deps=["model.latam_lakehouse.stg_x", "seed.latam_lakehouse.codes"],
            ),
            node(
                "snapshot",
                "snap_x",
                "snapshots/snapshots.yml",
                schema="snapshots",
                code='select * from "lakehouse"."silver"."stg_x"',
                deps=["model.latam_lakehouse.stg_x"],
                unique_key="id",
            ),
            node(
                "model",
                "mart_x",
                "models/gold/marts/mart_x.sql",
                mat="table",
                schema="gold",
                code='select i.id, f.score from "lakehouse"."silver"."int_x" i '
                'join "lakehouse"."features"."feat_x" f using (id)',
                deps=["model.latam_lakehouse.int_x", "model.latam_lakehouse.feat_x"],
            ),
            node(
                "model",
                "feat_x",
                "models/features/feat_x.sql",
                mat="external",
                schema="features",
                code='select id, v * 10 as score from "lakehouse"."silver"."int_x"',
                deps=["model.latam_lakehouse.int_x"],
            ),
            node(
                "test",
                "not_null_int_x_label",
                "models/silver/conformed/_x.yml",
                mat="test",
                code='select * from "lakehouse"."silver"."int_x" where label is null',
                deps=["model.latam_lakehouse.int_x"],
                severity="ERROR",
            ),
            node(
                "test",
                "unique_mart_x_id",
                "models/gold/_x.yml",
                mat="test",
                code='select id from "lakehouse"."gold"."mart_x" group by id having count(*) > 1',
                deps=["model.latam_lakehouse.mart_x"],
                severity="WARN",
            ),
        ]
    )
    for n in nodes.values():
        n["root_path"] = str(tmp_path)
    child_map: dict[str, list[str]] = {k: [] for k in nodes}
    for k, n in nodes.items():
        for d in n["depends_on"]["nodes"]:
            child_map[d].append(k)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"metadata": {"project_name": PROJECT}, "nodes": nodes, "child_map": child_map})
    )
    return pipe.Pipeline(manifest, tmp_path / "lakehouse.duckdb")


def test_database_must_be_named_lakehouse(tmp_path, project):
    with pytest.raises(ValueError, match="lakehouse.duckdb"):
        pipe.Pipeline(project.manifest_path, tmp_path / "other.duckdb")


def test_nodes_fall_into_the_dag_task_groups(project):
    layers = {project.name(k): pipe.layer_of(project.nodes[k]) for k in project.buildable()}
    assert layers == {
        "codes": "seeds",
        "stg_x": "silver",
        "int_x": "silver",
        "snap_x": "snapshots",
        "mart_x": "gold",
        "feat_x": "features_graph_knowledge",
    }
    assert [project.name(k) for k in project.layer_nodes("silver")] == ["stg_x", "int_x"]


def test_forward_dependency_is_reported(project):
    fwd = project.forward_dependencies()
    assert fwd.to_dict("records") == [
        {
            "node": "mart_x",
            "layer": "gold",
            "reads": "feat_x",
            "built_in": "features_graph_knowledge",
        }
    ]


def test_seed_types_follow_dbt_duckdb(project):
    project.build_layer("seeds", verbose=False)
    types = dict(
        project.q(
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'codes'"
        ).values
    )
    assert types == {
        "code": "VARCHAR",
        "label": "VARCHAR",
        "flag": "BOOLEAN",
        "n": "INTEGER",
        "x": "DOUBLE",
    }
    assert project.q("select code from {codes} order by code")["code"].tolist() == ["00", "05"]


def test_layers_build_with_materializations_and_pull_forward(project):
    for layer in ("seeds", "silver", "snapshots"):
        project.build_layer(layer, verbose=False)
    kinds = dict(
        project.q(
            "select table_name, table_type from information_schema.tables "
            "where table_schema in ('silver', 'snapshots')"
        ).values
    )
    assert kinds == {"stg_x": "VIEW", "int_x": "BASE TABLE", "snap_x": "BASE TABLE"}
    gold = project.build_layer("gold", verbose=False)
    assert gold[["node", "pulled_forward"]].values.tolist() == [["feat_x", True], ["mart_x", False]]
    assert project.rows("mart_x") == 3
    assert project.log()["node"].tolist()[-2:] == ["feat_x", "mart_x"]


def test_snapshot_first_load_has_dbt_columns(project):
    project.ensure(project.key("snap_x"))
    snap = project.q("select * from {snap_x} order by id")
    assert {"dbt_scd_id", "dbt_updated_at", "dbt_valid_from", "dbt_valid_to"} <= set(snap.columns)
    assert snap["dbt_valid_to"].isna().all()
    assert snap["dbt_scd_id"].nunique() == 3


def test_tests_run_after_their_layer(project):
    project.ensure_until("gold")
    silver = project.run_tests("silver")
    assert silver[["test", "failures", "status"]].values.tolist() == [
        ["not_null_int_x_label", 1, "fail"]
    ]
    gold = project.run_tests("gold")
    assert gold[["status", "severity"]].values.tolist() == [["pass", "WARN"]]
    assert len(project.tests()) == 2


def test_lineage_and_catalog(project):
    lin = project.lineage("int_x")
    assert lin == {"upstream": ["codes", "stg_x"], "downstream": ["feat_x", "mart_x"]}
    cat = project.catalog()
    assert len(cat) == 6
    assert cat.loc[cat.node == "int_x", "children"].item() == 2


def test_profile_counts_nulls(project):
    project.ensure_until("silver")
    prof = project.profile("int_x").set_index("column_name")
    assert prof.loc["label", "null_pct"] == pytest.approx(100 / 3, abs=0.01)


def test_mask_hides_personal_data_and_free_text():
    df = pd.DataFrame(
        {
            "first_name": ["Ana"],
            "email": ["a.b@x.co"],
            "description": ["x" * 40],
            "email_token": ["0123456789abcdef"],
            "customer_id": ["CLI-1"],
        }
    )
    out = pipe.mask(df, {"first_name", "email", "description"})
    assert out.iloc[0].tolist() == ["AAA", "A.A@A.AA", "‹text, 40 chars›", "012345…", "CLI-1"]


def test_restricted_columns_come_from_the_seed():
    cols = pipe.restricted_columns(pipe.repo_root())
    assert {"first_name", "document_number", "full_text", "ip_address"} <= cols


def test_build_set_rebuilds_named_nodes_in_dependency_order(project):
    project.ensure_until("silver")
    out = project.build_set(["int_x", "stg_x"], verbose=False)
    assert out["node"].tolist() == ["stg_x", "int_x"]
    assert not out["pulled_forward"].any()
