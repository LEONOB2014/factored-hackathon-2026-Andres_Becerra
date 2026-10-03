"""Entity graph load: lakehouse graph exports -> Neo4j (tokens only, broken FKs already excluded).

Loads the demo subset (deterministic 2 % customer sample and everything they touch) so a laptop Neo4j stays
responsive; production loads the full graph with neo4j-admin import. Constraints first, then batched UNWIND
MERGE writes, then a reconciliation of node/edge counts against the lakehouse.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, GRAPH, LAKEHOUSE, PLATFORM_PY


@dag(
    dag_id="graph_load",
    schedule=[LAKEHOUSE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "ml-engineering"},
    tags=["graph", "neo4j", "gnn"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def graph_load():
    @task.external_python(
        python=PLATFORM_PY, expect_airflow=False, outlets=[GRAPH], pool="neo4j_writer"
    )
    def load(lineage_run_id: str, sample_pct: int = 2) -> dict:
        import duckdb

        from latam_platform import config, ops

        lake = config.LAKE / "graph"
        con = duckdb.connect()
        con.sql(f"""CREATE TEMP TABLE edges AS
                    SELECT * FROM '{lake}/graph_edges.parquet'
                    WHERE src_type <> 'customer' OR hash(src_id) % 100 < {sample_pct}""")
        con.sql("""CREATE TEMP TABLE edges_s AS
                   SELECT e.* FROM edges e
                   WHERE e.src_type = 'customer'
                      OR e.src_id IN (SELECT dst_id FROM edges WHERE src_type = 'customer')""")
        con.sql(f"""CREATE TEMP TABLE nodes AS
                    SELECT n.* FROM '{lake}/graph_nodes.parquet' n
                    WHERE (n.node_type, n.node_id) IN (SELECT src_type, src_id FROM edges_s
                                                       UNION SELECT dst_type, dst_id FROM edges_s)""")
        neo = ops.neo4j_driver()
        labels = [r[0] for r in con.sql("SELECT DISTINCT node_type FROM nodes").fetchall()]
        for lbl in labels:
            neo.execute_query(
                f"CREATE CONSTRAINT {lbl}_id IF NOT EXISTS FOR (n:{lbl.capitalize()}) REQUIRE n.id IS UNIQUE"
            )
        for lbl in labels:
            rows = (
                con.sql(f"SELECT node_id AS id, features FROM nodes WHERE node_type = '{lbl}'")
                .df()
                .to_dict("records")
            )
            for i in range(0, len(rows), 5000):
                neo.execute_query(
                    f"UNWIND $rows AS r MERGE (n:{lbl.capitalize()} {{id: r.id}}) SET n.features = r.features",
                    rows=rows[i : i + 5000],
                )
        rels = con.sql("SELECT DISTINCT src_type, rel, dst_type FROM edges_s").fetchall()
        n_edges = 0
        for s, r, d in rels:
            rows = (
                con.sql(f"""SELECT src_id AS s, dst_id AS d, cast(ts AS varchar) AS ts, weight AS w, label AS y
                               FROM edges_s WHERE src_type='{s}' AND rel='{r}' AND dst_type='{d}'""")
                .df()
                .to_dict("records")
            )
            for i in range(0, len(rows), 5000):
                neo.execute_query(
                    f"UNWIND $rows AS r MATCH (a:{s.capitalize()} {{id: r.s}}) MATCH (b:{d.capitalize()} {{id: r.d}}) "
                    f"CREATE (a)-[:{r.upper()} {{ts: r.ts, weight: r.w, label: r.y}}]->(b)",
                    rows=rows[i : i + 5000],
                )
            n_edges += len(rows)
        counts, _, _ = neo.execute_query("MATCH (n) RETURN count(n) AS nodes")
        neo.close()
        out = {
            "sample_pct": sample_pct,
            "nodes_expected": con.sql("SELECT count(*) FROM nodes").fetchone()[0],
            "edges_loaded": n_edges,
            "nodes_in_neo4j": counts[0]["nodes"],
        }
        ops.ledger("graph.loaded", "neo4j", out, lineage_run_id)
        return out

    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def reset_entity_graph() -> int:
        """Entity graph is rebuilt per load (idempotent); the KB graph (Document/Chunk/Entity) is untouched."""
        from latam_platform import ops

        neo = ops.neo4j_driver()
        total = 0
        for lbl in [
            "Customer",
            "Product",
            "Merchant",
            "Branch",
            "Agent",
            "Campaign",
            "Country",
            "Complaint",
            "Ip",
        ]:
            while True:
                recs, _, _ = neo.execute_query(
                    f"MATCH (n:{lbl}) WITH n LIMIT 20000 DETACH DELETE n RETURN count(*) AS c"
                )
                total += recs[0]["c"]
                if recs[0]["c"] == 0:
                    break
        neo.close()
        return total

    reset_entity_graph() >> load(lineage_run_id="{{ run_id }}")


graph_load()
