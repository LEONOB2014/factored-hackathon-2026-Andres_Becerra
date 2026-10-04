"""Replay the `dbt_lakehouse` DAG in a temporary DuckDB, one compiled statement at a time (pipeline series).

Airflow runs the dbt project through Cosmos in seven task groups (`LAYERS` in
platform/airflow/dags/dbt_lakehouse.py). This module runs the very same SQL without Airflow and without dbt's
runner: `compile_project` asks dbt to render every model (macros resolved, refs and sources turned into relation
names and `read_parquet` calls), and `Pipeline` executes each compiled statement in a scratch database named
`lakehouse.duckdb`, so the compiled references (`"lakehouse"."silver"."typed_customers"`) resolve. The real lake is
only read; external models become tables in the scratch database instead of Parquet files in the shared lake.

What dbt would add and the emulator reproduces explicitly:
* seeds are loaded from their CSV with dbt-duckdb's types (leading-zero codes stay text, see `_seed_type`);
* a snapshot's first run is the source relation plus `dbt_scd_id`, `dbt_updated_at`, `dbt_valid_from` and an empty
  `dbt_valid_to` (later runs would close changed rows; the walkthrough builds once);
* data tests run after their layer, as Cosmos does with `TestBehavior.AFTER_ALL`; a test fails when its compiled
  query returns rows.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

# The task groups of dbt_lakehouse, in order. A node belongs to the first layer whose selector matches it.
LAYERS: list[tuple[str, tuple[str, ...]]] = [
    ("seeds", ("seed",)),
    ("silver", ("models/silver/",)),
    ("snapshots", ("snapshot",)),
    ("gold", ("models/gold/",)),
    ("features_graph_knowledge", ("models/features/", "models/graph/", "models/knowledge/")),
    ("privacy_serving", ("models/privacy/", "models/serving/")),
    ("audit", ("models/audit/",)),
]
LAYER_NAMES = [name for name, _ in LAYERS]

# Bounded profile: a 16 GB laptop running the Docker stack must not swap (platform-checks gotchas).
SETTINGS = {
    "memory_limit": "4GB",
    "max_temp_directory_size": "6GB",
    "threads": "4",
    "preserve_insertion_order": "false",
}

LOG_TABLE = "main._pipeline_runs"
TEST_TABLE = "main._pipeline_tests"

_INT = re.compile(r"^-?(0|[1-9][0-9]*)$")
_NUM = re.compile(r"^-?[0-9]*\.[0-9]+$|^-?[0-9]+\.[0-9]*$")
_BOOL = {"true", "false"}


def repo_root(start: Path | None = None) -> Path:
    """The repository root: the first parent holding both eda/ and platform/."""
    p = (start or Path(__file__)).resolve()
    for parent in [p, *p.parents]:
        if (parent / "eda").is_dir() and (parent / "platform").is_dir():
            return parent
    raise FileNotFoundError("repository root not found")


def default_workdir(repo: Path) -> Path:
    return Path(os.environ.get("LATAM_PIPELINE_DIR", repo / "data" / "tmp" / "pipeline")).resolve()


def default_lake(repo: Path) -> Path:
    return Path(os.environ.get("LATAM_LAKE_DIR", repo / "data" / "lake")).resolve()


def compile_project(repo: Path, workdir: Path, lake: Path) -> Path:
    """Render every node with `dbt compile` (no Airflow, no model runs) and return the manifest path.

    dbt opens `<workdir>/lakehouse.duckdb` to compile, so call this before `Pipeline` opens it.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    dbt = repo / "platform" / ".venv" / "bin" / "dbt"
    if not dbt.exists():
        raise FileNotFoundError(f"{dbt} not found: run `uv sync` in platform/ first")
    env = {
        **os.environ,
        "LATAM_LAKE_DIR": str(lake),
        "LATAM_DUCKDB_PATH": str(workdir / "lakehouse.duckdb"),
        "DBT_PROFILES_DIR": ".",
    }
    target = workdir / "target"
    subprocess.run(
        [str(dbt), "compile", "--quiet", "--target-path", str(target)],
        cwd=repo / "platform" / "dbt",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return target / "manifest.json"


def session(cwd: Path | None = None, recompile: bool = False) -> Pipeline:
    """Open the scratch lakehouse for a notebook: compile the project first if there is no manifest yet."""
    repo = repo_root(Path(cwd or Path.cwd()))
    work, lake = default_workdir(repo), default_lake(repo)
    manifest = work / "target" / "manifest.json"
    if recompile or not manifest.exists():
        compile_project(repo, work, lake)
    pl = Pipeline(manifest, work / "lakehouse.duckdb")
    pl.repo, pl.lake = repo, lake
    pl.restricted = restricted_columns(repo)
    return pl


def layer_of(node: dict) -> str | None:
    kind = node["resource_type"]
    path = node.get("original_file_path", "")
    for name, selectors in LAYERS:
        for sel in selectors:
            if kind == sel or (
                sel.startswith("models/") and kind == "model" and path.startswith(sel)
            ):
                return name
    return None


def _seed_type(values: pd.Series) -> str:
    """dbt-duckdb's seed typing as observed in the lakehouse: codes with leading zeros stay text."""
    v = values.dropna().astype(str).str.strip()
    v = v[v != ""]
    if v.empty:
        return "VARCHAR"
    if v.str.lower().isin(_BOOL).all():
        return "BOOLEAN"
    if v.str.match(_INT).all():
        return "INTEGER"
    if (v.str.match(_INT) | v.str.match(_NUM)).all():
        return "DOUBLE"
    return "VARCHAR"


@dataclass
class Built:
    node: str
    layer: str
    materialized: str
    rows: int | None
    seconds: float
    pulled_forward: bool = False


class Pipeline:
    """A scratch lakehouse built node by node from a compiled dbt manifest."""

    def __init__(self, manifest: Path, db: Path, settings: dict[str, str] | None = None):
        self.manifest_path = Path(manifest)
        self.m = json.loads(self.manifest_path.read_text())
        self.db = Path(db)
        if self.db.stem != "lakehouse":
            raise ValueError(
                "the scratch database must be named lakehouse.duckdb (compiled refs use that catalog)"
            )
        self.con = duckdb.connect(str(self.db))
        for k, v in {**SETTINGS, **(settings or {})}.items():
            self.con.sql(f"SET {k} = '{v}'")
        self.con.sql("SET enable_progress_bar = false")
        self.con.sql(
            f"""CREATE TABLE IF NOT EXISTS {LOG_TABLE} (node VARCHAR, layer VARCHAR, materialized VARCHAR,
                rows BIGINT, seconds DOUBLE, pulled_forward BOOLEAN, built_at TIMESTAMP)"""
        )
        self.con.sql(
            f"""CREATE TABLE IF NOT EXISTS {TEST_TABLE} (test VARCHAR, layer VARCHAR, attached_to VARCHAR,
                severity VARCHAR, failures BIGINT, status VARCHAR, seconds DOUBLE, error VARCHAR)"""
        )
        project = self.m["metadata"].get("project_name") or "latam_lakehouse"
        self.nodes = {
            k: n
            for k, n in self.m["nodes"].items()
            if n["resource_type"] in ("model", "seed", "snapshot", "test")
            and n["package_name"] == project
        }

    # ------------------------------------------------------------------ graph
    def name(self, key: str) -> str:
        return self.nodes[key]["name"] if key in self.nodes else key.split(".")[-1]

    def key(self, name: str) -> str:
        if name in self.nodes:
            return name
        hits = [
            k for k, n in self.nodes.items() if n["name"] == name and n["resource_type"] != "test"
        ]
        if len(hits) != 1:
            raise KeyError(f"{name!r}: {len(hits)} matching nodes")
        return hits[0]

    def deps(self, key: str) -> list[str]:
        return [d for d in self.nodes[key]["depends_on"].get("nodes", []) if d in self.nodes]

    def relation(self, key: str) -> str:
        n = self.nodes[key]
        return (
            n.get("relation_name")
            or f'"{n["database"]}"."{n["schema"]}"."{n.get("alias") or n["name"]}"'
        )

    def buildable(self) -> list[str]:
        return [k for k, n in self.nodes.items() if n["resource_type"] != "test"]

    def topo(self, keys: list[str]) -> list[str]:
        """Order keys so each comes after its dependencies within the set (stable by name)."""
        keyset, done, out = set(keys), set(), []

        def visit(k: str, stack: tuple = ()):
            if k in done:
                return
            if k in stack:
                raise ValueError(f"cycle at {k}")
            for d in sorted(self.deps(k)):
                if d in keyset:
                    visit(d, (*stack, k))
            done.add(k)
            out.append(k)

        for k in sorted(keys, key=self.name):
            visit(k)
        return out

    def layer_nodes(self, layer: str) -> list[str]:
        return self.topo([k for k in self.buildable() if layer_of(self.nodes[k]) == layer])

    def forward_dependencies(self) -> pd.DataFrame:
        """Edges where a node reads a node that Airflow builds in a LATER task group (stale or missing input)."""
        rank = {name: i for i, name in enumerate(LAYER_NAMES)}
        rows = []
        for k in self.buildable():
            lk = layer_of(self.nodes[k])
            for d in self.deps(k):
                ld = layer_of(self.nodes[d])
                if lk and ld and rank[ld] > rank[lk]:
                    rows.append(
                        {"node": self.name(k), "layer": lk, "reads": self.name(d), "built_in": ld}
                    )
        return pd.DataFrame(rows, columns=["node", "layer", "reads", "built_in"])

    def lineage(self, name: str, depth: int = 99) -> dict[str, list[str]]:
        k = self.key(name)
        children = self.m.get("child_map", {})

        def walk(start, nxt):
            seen, frontier = set(), [start]
            for _ in range(depth):
                frontier = [
                    c for f in frontier for c in nxt(f) if c in self.nodes and c not in seen
                ]
                if not frontier:
                    break
                seen.update(frontier)
            return sorted(self.name(s) for s in seen if self.nodes[s]["resource_type"] != "test")

        return {
            "upstream": walk(k, self.deps),
            "downstream": walk(k, lambda x: children.get(x, [])),
        }

    def catalog(self) -> pd.DataFrame:
        rows = []
        for k in self.buildable():
            n = self.nodes[k]
            rows.append(
                {
                    "layer": layer_of(n),
                    "node": n["name"],
                    "kind": n["resource_type"],
                    "materialized": n["config"].get("materialized"),
                    "schema": n["schema"],
                    "path": n.get("original_file_path"),
                    "description": (n.get("description") or "").strip().split("\n")[0][:160],
                    "parents": len(self.deps(k)),
                    "children": len(
                        [
                            c
                            for c in self.m.get("child_map", {}).get(k, [])
                            if self.nodes.get(c, {}).get("resource_type") not in (None, "test")
                        ]
                    ),
                }
            )
        df = pd.DataFrame(rows)
        df["layer"] = pd.Categorical(df["layer"], LAYER_NAMES, ordered=True)
        return df.sort_values(["layer", "node"]).reset_index(drop=True)

    def sql(self, name: str) -> str:
        n = self.nodes[self.key(name)]
        return (n.get("compiled_code") or n.get("raw_code") or "").strip()

    # ------------------------------------------------------------------ state
    def exists(self, key: str) -> bool:
        n = self.nodes[key]
        return bool(
            self.con.sql(
                """SELECT count(*) FROM information_schema.tables
                   WHERE table_catalog = 'lakehouse' AND table_schema = ? AND table_name = ?""",
                params=[n["schema"], n.get("alias") or n["name"]],
            ).fetchone()[0]
        )

    def log(self) -> pd.DataFrame:
        return self.con.sql(f"SELECT * FROM {LOG_TABLE} ORDER BY built_at").df()

    def tests(self) -> pd.DataFrame:
        return self.con.sql(f"SELECT * FROM {TEST_TABLE} ORDER BY layer, status DESC, test").df()

    # ------------------------------------------------------------------ build
    def _create(self, key: str) -> str:
        n = self.nodes[key]
        mat = n["config"].get("materialized")
        rel = self.relation(key)
        self.con.sql(f'CREATE SCHEMA IF NOT EXISTS "lakehouse"."{n["schema"]}"')
        if n["resource_type"] == "seed":
            path = Path(n["root_path"]) / n["original_file_path"]
            raw = self.con.sql(
                "SELECT * FROM read_csv(?, all_varchar = true, header = true)", params=[str(path)]
            ).df()
            types = {c.lower(): t for c, t in (n["config"].get("column_types") or {}).items()}
            cols = ", ".join(
                f'try_cast(nullif("{c}", \'\') AS {types.get(c.lower(), _seed_type(raw[c]))}) AS "{c}"'
                for c in raw.columns
            )
            self.con.sql(
                f"CREATE OR REPLACE TABLE {rel} AS SELECT {cols} FROM read_csv(?, all_varchar = true, header = true)",
                params=[str(path)],
            )
            return "seed"
        code = _body(n["compiled_code"])
        if n["resource_type"] == "snapshot":
            uk = n["config"]["unique_key"]
            self.con.sql(
                f"""CREATE OR REPLACE TABLE {rel} AS
                    WITH src AS (\n{code}\n), ts AS (SELECT current_timestamp::TIMESTAMP AS t)
                    SELECT src.*,
                           md5(coalesce(CAST({uk} AS VARCHAR), '') || '|' || coalesce(CAST(ts.t AS VARCHAR), ''))
                               AS dbt_scd_id,
                           ts.t AS dbt_updated_at, ts.t AS dbt_valid_from, NULL::TIMESTAMP AS dbt_valid_to
                    FROM src, ts"""
            )
            return "snapshot"
        if mat == "view":
            self.con.sql(f"CREATE OR REPLACE VIEW {rel} AS {code}")
        else:  # table, and external (kept in the scratch database instead of the shared lake)
            self.con.sql(f"CREATE OR REPLACE TABLE {rel} AS {code}")
        return mat

    def build(self, name: str, *, pulled_forward: bool = False, count: bool = True) -> Built:
        key = self.key(name)
        n = self.nodes[key]
        t0 = time.perf_counter()
        mat = self._create(key)
        secs = time.perf_counter() - t0
        rows = None
        if count:
            rows = self.con.sql(f"SELECT count(*) FROM {self.relation(key)}").fetchone()[0]
        b = Built(n["name"], layer_of(n) or "?", mat, rows, round(secs, 2), pulled_forward)
        self.con.execute(
            f"INSERT INTO {LOG_TABLE} VALUES (?, ?, ?, ?, ?, ?, now()::TIMESTAMP)",
            [b.node, b.layer, b.materialized, b.rows, b.seconds, b.pulled_forward],
        )
        return b

    def ensure(self, key: str, layer: str | None = None) -> list[Built]:
        """Build `key` and anything it reads that does not exist yet (dependencies first). With `layer`, a node
        that Airflow builds in a LATER task group is marked `pulled_forward`."""
        rank = {name: i for i, name in enumerate(LAYER_NAMES)}
        out: list[Built] = []
        for d in sorted(self.deps(key)):
            if not self.exists(d):
                out += self.ensure(d, layer)
        if not self.exists(key):
            own = layer_of(self.nodes[key])
            pf = layer is not None and own is not None and rank[own] > rank[layer]
            out.append(self.build(key, pulled_forward=pf))
        return out

    def build_layer(
        self, layer: str, *, rebuild: bool = False, verbose: bool = True
    ) -> pd.DataFrame:
        """Build one Airflow task group in dependency order. A node it reads from a LATER group is built first and
        marked `pulled_forward`: in Airflow it would be read stale from the previous run, or be missing."""
        built: list[Built] = []
        for k in self.layer_nodes(layer):
            if not rebuild and self.exists(k):
                continue
            for d in sorted(self.deps(k)):
                if not self.exists(d):
                    built += self.ensure(d, layer)
            built.append(self.build(k))
        return _report(built, verbose)

    def build_set(self, names: list[str], *, verbose: bool = True) -> pd.DataFrame:
        """(Re)build the named nodes in dependency order; anything else they read is built only if missing.
        A notebook uses it to show the build of the part of a task group it explains."""
        keys = self.topo([self.key(n) for n in names])
        built: list[Built] = []
        for k in keys:
            for d in sorted(self.deps(k)):
                if d not in keys and not self.exists(d):
                    built += self.ensure(d, layer_of(self.nodes[k]))
            built.append(self.build(k))
        return _report(built, verbose)

    def ensure_until(self, layer: str, verbose: bool = False) -> None:
        """Make sure every layer up to and including `layer` exists (to run one notebook on its own)."""
        for name in LAYER_NAMES[: LAYER_NAMES.index(layer) + 1]:
            self.build_layer(name, verbose=verbose)

    # ------------------------------------------------------------------ tests
    def layer_tests(self, layer: str) -> list[str]:
        """Tests whose models are all built by the end of `layer` and not before (Cosmos AFTER_ALL)."""
        rank = {name: i for i, name in enumerate(LAYER_NAMES)}
        out = []
        for k, n in self.nodes.items():
            if n["resource_type"] != "test":
                continue
            ranks = [rank.get(layer_of(self.nodes[d]), -1) for d in self.deps(k)]
            if ranks and max(ranks) == rank[layer]:
                out.append(k)
        return sorted(out, key=self.name)

    def run_tests(self, layer: str) -> pd.DataFrame:
        rows = []
        for k in self.layer_tests(layer):
            n = self.nodes[k]
            attached = n.get("attached_node") or (self.deps(k)[0] if self.deps(k) else "")
            sev = str(n["config"].get("severity", "ERROR")).upper()
            t0 = time.perf_counter()
            err, failures = None, None
            try:
                failures = self.con.sql(
                    f"SELECT count(*) FROM (\n{_body(n['compiled_code'])}\n) AS t"
                ).fetchone()[0]
            except duckdb.Error as e:
                err = str(e).splitlines()[0][:300]
            status = (
                "error"
                if err
                else ("pass" if failures == 0 else ("warn" if sev == "WARN" else "fail"))
            )
            row = [
                n["name"],
                layer,
                self.name(attached) if attached else "",
                sev,
                failures,
                status,
                round(time.perf_counter() - t0, 2),
                err,
            ]
            self.con.execute(f"DELETE FROM {TEST_TABLE} WHERE test = ?", [n["name"]])
            self.con.execute(f"INSERT INTO {TEST_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
            rows.append(
                dict(
                    zip(
                        [
                            "test",
                            "layer",
                            "attached_to",
                            "severity",
                            "failures",
                            "status",
                            "seconds",
                            "error",
                        ],
                        row,
                        strict=True,
                    )
                )
            )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ inspection
    def q(self, sql: str) -> pd.DataFrame:
        """Run a query; `{name}` placeholders become that node's relation: q("select * from {dim_customer}")."""
        for nm in set(re.findall(r"\{([a-z_0-9]+)\}", sql)):
            sql = sql.replace("{" + nm + "}", self.relation(self.key(nm)))
        return self.con.sql(sql).df()

    def rows(self, name: str) -> int:
        return self.con.sql(f"SELECT count(*) FROM {self.relation(self.key(name))}").fetchone()[0]

    def columns(self, name: str) -> pd.DataFrame:
        k = self.key(name)
        n = self.nodes[k]
        df = self.con.sql(
            """SELECT column_name, data_type FROM information_schema.columns
               WHERE table_catalog = 'lakehouse' AND table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
            params=[n["schema"], n.get("alias") or n["name"]],
        ).df()
        docs = n.get("columns") or {}
        df["description"] = [(docs.get(c) or {}).get("description", "") for c in df["column_name"]]
        return df

    def profile(self, name: str) -> pd.DataFrame:
        """One row per column: type, null share, distinct values, min and max (as text)."""
        rel = self.relation(self.key(name))
        cols = self.columns(name)
        total = self.rows(name)
        parts = []
        for c, t in zip(cols["column_name"], cols["data_type"], strict=True):
            simple = not any(x in t for x in ("[]", "STRUCT", "MAP", "UNION"))
            mm = f'min("{c}")::VARCHAR, max("{c}")::VARCHAR' if simple else "NULL, NULL"
            ad = f'approx_count_distinct("{c}")' if simple else "NULL"
            parts.append(f"""SELECT '{c}' AS column_name, '{t}' AS data_type, count("{c}") AS non_null,
                             {ad} AS distinct_approx, {mm} FROM {rel}""")
        df = self.con.sql(" UNION ALL ".join(parts)).df() if parts else pd.DataFrame()
        df.columns = ["column_name", "data_type", "non_null", "distinct_approx", "min", "max"]
        df["null_pct"] = (100 * (1 - df["non_null"] / total)).round(3) if total else None
        return df

    def safe(self, df: pd.DataFrame) -> pd.DataFrame:
        """`df` with personal data and free text masked, for display in committed notebooks."""
        restricted = getattr(self, "restricted", None) or restricted_columns(repo_root())
        return mask(df, restricted)

    def close(self) -> None:
        self.con.close()


# ---------------------------------------------------------------------- privacy for committed outputs
def restricted_columns(repo: Path) -> set[str]:
    seed = repo / "platform" / "dbt" / "seeds" / "restricted_pii_columns.csv"
    names = set(pd.read_csv(seed)["column_name"].str.lower())
    return names | {"subject", "transcript_text", "ip_address_token"}


def mask(df: pd.DataFrame, restricted: set[str]) -> pd.DataFrame:
    """Hide personal data and free text: restricted columns keep only their shape, tokens are shortened."""
    out = df.copy()
    for c in out.columns:
        lc = str(c).lower()
        if lc in restricted:
            out[c] = out[c].map(_shape)
        elif lc.endswith("_token"):
            out[c] = out[c].map(lambda v: v if v is None or pd.isna(v) else f"{str(v)[:6]}…")
    return out


def _report(built: list[Built], verbose: bool) -> pd.DataFrame:
    if verbose:
        for b in built:
            flag = "  (pulled forward)" if b.pulled_forward else ""
            rows = "" if b.rows is None else f"{b.rows:,}"
            print(f"  {b.materialized:9s} {b.node:45s} {rows:>14} rows {b.seconds:7.1f}s{flag}")
    cols = ["node", "layer", "materialized", "rows", "seconds", "pulled_forward"]
    return pd.DataFrame([b.__dict__ for b in built], columns=cols)


def _body(code: str) -> str:
    """A compiled statement ready to be wrapped: no trailing semicolon (a trailing comment is closed by the caller's
    newline)."""
    return code.strip().rstrip(";").strip()


def _shape(v):
    if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
        return v
    s = str(v)
    if len(s) > 24:
        return f"‹text, {len(s)} chars›"
    return re.sub(r"[0-9]", "9", re.sub(r"[^\W\d_]", "A", s))
