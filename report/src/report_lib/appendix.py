"""Generate the data-driven appendices: traceability (A), claims ledger (B), per-country tables (C), software (D).

texgen.main() calls render_all() on every build, so the appendices always describe the claims, the notebook map, the
stored country tables and the toolchain of that build. Each output is a LaTeX fragment that an appendix file inputs
from build/generated/appendices/; the hand-written prose around it lives in tex/appendices/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pandas as pd

from report_lib import protocol, sources
from report_lib.build import CENSUS, CONSTANT
from report_lib.manifest import Claim
from report_lib.paths import CONF, GENERATED, REPO, REPORT, TABLES, TEX
from report_lib.texgen import breakable_path, claim_fields, render_table, tex_escape

STATUS_MARK = {"exploratory": "E", "registered": "R", "positive-control": "P"}
SHORT_REASON = {CENSUS: "census", CONSTANT: "constant"}
COUNTRIES = ("all", "ar", "co", "mx")
TRANSPOSED = {"profile", "contract", "anomalies"}  # mixed columns: dates, labels and numbers
# Packages whose versions decide a number in the report: estimation, data access, LaTeX generation.
PACKAGES = (
    "duckdb", "lifelines", "matplotlib", "numpy", "pandas", "pyarrow", "pydantic", "pylatexenc", "pyod",
    "ruptures", "scikit-learn", "scipy", "statsmodels",
)  # fmt: skip


def longtable(spec: str, head: list[str], rows: list[str], caption: str, label: str) -> str:
    """A booktabs longtable that repeats its header on every page; rows are pre-rendered LaTeX lines."""
    header = " & ".join(head) + r" \\"
    ncol = len(head)
    return "\n".join([
        r"{\footnotesize\setlength{\tabcolsep}{3pt}", f"\\begin{{longtable}}{{{spec}}}",
        f"\\caption{{{caption}}}\\label{{tab:{label}}}\\\\", r"\toprule", header, r"\midrule", r"\endfirsthead",
        f"\\multicolumn{{{ncol}}}{{l}}{{\\emph{{\\Cref{{tab:{label}}}, continued}}}}\\\\", r"\toprule", header,
        r"\midrule", r"\endhead", r"\bottomrule", r"\endfoot", *rows, r"\end{longtable}}",
    ])  # fmt: skip


def chapter_titles(tex: Path = TEX) -> dict[int, str]:
    """Chapter number -> its label, read from the chapter files."""
    out = {}
    for path in sorted((tex / "chapters").glob("*.tex")):
        m = re.search(r"\\label\{(ch:[^}]+)\}", path.read_text())
        if m:
            out[int(path.name[:2])] = m.group(1)
    return out


# --- A: traceability ---------------------------------------------------------------------------------------------


def traceability(path: Path = CONF / "notebook_map.csv") -> str:
    frame = pd.read_csv(path, keep_default_na=False)
    rows = []
    for notebook, group in frame.groupby("notebook", sort=True):
        rows.append(f"\\multicolumn{{3}}{{@{{}}l}}{{\\textbf{{\\nolinkurl{{{notebook}}}}}}}\\\\*")
        for r in group.itertuples(index=False):
            where = (
                f"\\Cref{{{r.report_label}}}"
                if r.report_label
                else f"\\emph{{{tex_escape(r.out_of_scope_reason)}}}"
            )
            indent = r"\quad " if int(r.level) > 1 else ""
            rows.append(f"{r.level} & {indent}{tex_escape(r.heading)} & {where} \\\\")
    caption = (
        "Every level-one and level-two heading of the notebook sources and where the report treats it. Source: "
        f"\\texttt{{{tex_escape(sources.rel(path))}}}, SHA-256 \\texttt{{{sources.sha256(path)[:12]}}}."
    )
    spec = r"@{}r>{\raggedright\arraybackslash}p{0.62\linewidth}>{\raggedright\arraybackslash}p{0.28\linewidth}@{}"
    return longtable(spec, ["Level", "Heading", "Treated in"], rows, caption, "app-traceability")


# --- B: claims ledger --------------------------------------------------------------------------------------------


def claim_value(c: Claim) -> tuple[str, str]:
    """The headline value of a claim and its uncertainty, as the ledger prints them."""
    f = claim_fields(c)
    if c.kind == "proportion":
        value = f"{f['share']} ({f['num']}/{f['den']})"
    elif c.kind == "rate":
        value = f"{f['events']}/{f['exposure']}"
    elif c.kind == "test":
        value = f"{f['statistic']}"
        return value, f"$p$ {f['p']}, $q$ {f['q']}"
    elif c.kind in ("difference", "ratio", "metric"):
        value = f["estimate"]
    else:
        value = f["value"]
    if c.unit:
        value += f" {tex_escape(c.unit)}"
    return value, f.get("ci", "")


def claim_method(c: Claim) -> str:
    if c.interval_method:
        unit = f", {c.cluster_unit}" if c.cluster_unit and c.cluster_unit != "none" else ""
        return tex_escape(c.interval_method + unit)
    if c.kind == "location":
        return tex_escape(c.method or "")
    if c.reason:
        return SHORT_REASON.get(c.reason, tex_escape(c.reason.split(":")[0].split(",")[0]))
    return "exact count" if c.kind == "count" else ""


def source_index(claims: dict[str, Claim]) -> dict[tuple[str, str], int]:
    """Number every distinct (path, digest) pair the claims were computed from, in path order."""
    pairs = sorted({(c.source_path, c.source_sha256) for c in claims.values()})
    return {p: n for n, p in enumerate(pairs, 1)}


def claims_ledger(claims: dict[str, Claim]) -> str:
    index = source_index(claims)
    labels = chapter_titles()
    parts = []
    spec = (r"@{}>{\raggedright\arraybackslash}p{0.34\linewidth}l>{\raggedright\arraybackslash}p{0.17\linewidth}"
            r">{\raggedright\arraybackslash}p{0.17\linewidth}>{\raggedright\arraybackslash}p{0.15\linewidth}r@{}")  # fmt: skip
    for chapter in sorted({c.chapter for c in claims.values()}):
        rows = []
        for cid in sorted(k for k, c in claims.items() if c.chapter == chapter):
            c = claims[cid]
            value, interval = claim_value(c)
            src = index[(c.source_path, c.source_sha256)]
            rows.append(f"\\nolinkurl{{{cid}}} & {STATUS_MARK[c.status]} & {value} & {interval} & "
                        f"{claim_method(c)} & S{src} \\\\")  # fmt: skip
        label = labels.get(chapter)
        title = f"\\Cref{{{label}}}: \\nameref{{{label}}}" if label else f"Chapter {chapter}"
        parts.append(f"\\section*{{{title}}}")
        caption = (
            f"Claims of \\cref{{{label}}}, \\nameref{{{label}}}."
            if label
            else f"Claims of chapter {chapter}."
        )
        parts.append(longtable(spec, ["Claim", "St.", "Value", "Interval", "Method", "Source"], rows, caption,
                               f"app-claims-{chapter:02d}"))  # fmt: skip
    src_rows = [
        f"S{n} & \\nolinkurl{{{path}}} & \\texttt{{{digest[:12]}}} & "
        f"{sum(1 for c in claims.values() if (c.source_path, c.source_sha256) == (path, digest))} \\\\"
        for (path, digest), n in index.items()
    ]
    parts.append(r"\section*{Sources}")
    parts.append(longtable(r"@{}r>{\raggedright\arraybackslash}p{0.62\linewidth}lr@{}",
                           ["", "Path", "SHA-256", "Claims"], src_rows,
                           "The artefacts the claims were computed from, with the first characters of their digests.",
                           "app-claims-sources"))  # fmt: skip
    return "\n\n".join(parts) + "\n"


# --- C: per-country tables ---------------------------------------------------------------------------------------


def _country(kind: str, tables: Path) -> pd.DataFrame:
    frames = [pd.read_csv(tables / f"country_{c}_{kind}.csv") for c in COUNTRIES]
    frame = pd.concat(frames, ignore_index=True)
    return frame[frame["dataset"] == "main"] if "dataset" in frame else frame


def _transpose(frame: pd.DataFrame, drop=("dataset",)) -> pd.DataFrame:
    t = frame.drop(columns=[c for c in drop if c in frame]).set_index("country").T
    t.index = [str(i).replace("_", " ") for i in t.index]
    t.index.name = "measure"
    return t.reset_index()[["measure", "ALL", "AR", "CO", "MX"]]


def _pivot(frame: pd.DataFrame, index: str, value: str) -> pd.DataFrame:
    p = frame.pivot_table(index=index, columns="country", values=value, aggfunc="first")
    return p.reindex(columns=["ALL", "AR", "CO", "MX"]).reset_index()


def per_country(tables: Path = TABLES, out_dir: Path = GENERATED) -> list[str]:
    """Combine the country series' stored tables (main copy) by market; returns the generated table labels."""
    src = out_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)

    def rel(kind: str) -> str:
        return (
            f"the stored tables \\texttt{{country\\_<scope>\\_{kind}.csv}} of "
            f"\\texttt{{{breakable_path(sources.rel(tables))}}}"
        )

    specs = [
        ("profile", _transpose(_country("profile", tables)),
         "Profile of each market, main copy: customers, activity, currencies and typical amounts."),
        ("size", _pivot(_country("size", tables).assign(
            table=lambda f: f["zone"] + " " + f["table"]), "table", "rows"),
         "Rows per table and zone of the lakehouse, by market."),
        ("reconciliation", _pivot(_country("reconciliation", tables), "table_name", "changed_pct_of_shared"),
         "Of the keys a table shares between the copies, the per cent whose row changed, by market."),
        ("contract", _transpose(_country("contract", tables)),
         "The source contract per market: partitions held under the bank-wide and the market's own baselines, "
         "reports of severity B, the amount scale relative to the bank and the largest monthly stability index."),
        ("rule-slo", _pivot(_country("rule_slo", tables), "rule_id", "country_rate_pct"),
         "Violation rate of each integrity rule, per cent of the rows it applies to, by market."),
        ("anomalies", _transpose(_country("anomalies", tables)),
         "Anomaly summary per market: abnormal days, change points, outlier shares and the enrichment of the "
         "forest's top decile in the money-laundering typology."),
        ("calendar", _pivot(_country("calendar_effects", tables), "term", "effect %"),
         "Calendar effects on daily transaction volume, per cent, by market. The p-values behind them are "
         "unadjusted; \\cref{sec:time-calendar} applies false-discovery control over the protocol's family."),
    ]  # fmt: skip
    kinds = {"profile": "profile", "size": "size", "reconciliation": "reconciliation", "contract": "contract",
             "rule-slo": "rule\\_slo", "anomalies": "anomalies", "calendar": "calendar\\_effects"}  # fmt: skip
    labels = []
    for name, frame, caption in specs:
        path = src / f"appc-{name}.csv"
        frame.to_csv(path, index=False)
        label = f"appc-{name}"
        render_table(
            path,
            label,
            f"{caption} Combined from {rel(kinds[name])}.",
            out_dir=out_dir,
            parse_numbers=name in TRANSPOSED,
        )
        labels.append(label)
    return labels


# --- D: software and data ----------------------------------------------------------------------------------------


def locked_versions(lock: Path) -> dict[str, str]:
    """Package versions a uv lock resolves on this platform: a lock may fork a package by platform markers."""
    from packaging.markers import Marker  # a dependency of matplotlib, always present

    out: dict[str, str] = {}
    for p in tomllib.loads(lock.read_text()).get("package", []):
        if "version" not in p:
            continue
        markers = p.get("resolution-markers")
        if markers is None or any(Marker(m).evaluate() for m in markers):
            out[p["name"]] = p["version"]
    return out


def _first_line(cmd: list[str]) -> str:
    exe = shutil.which(cmd[0]) or shutil.which(cmd[0], path="/Library/TeX/texbin")
    if not exe:
        return "not found"
    out = subprocess.run(
        [exe, *cmd[1:]], capture_output=True, text=True, check=False
    ).stdout.strip()
    return out.splitlines()[0] if out else "not found"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, cwd=REPO,
                          env=protocol.git_env()).stdout.strip()  # fmt: skip


def software() -> dict[str, str]:
    """Three fragments for Appendix D: toolchain and package versions, pinned data files, provenance."""
    report, eda = locked_versions(REPORT / "uv.lock"), locked_versions(REPO / "eda" / "uv.lock")
    py = (REPO / "eda" / ".python-version").read_text().strip()
    tools = [
        ("Python (report and eda environments)", py),
        ("TeX engine", _first_line(["pdftex", "--version"])),
        ("Bibliography", _first_line(["biber", "--version"])),
        ("Build driver", _first_line(["latexmk", "-v"]).strip("- ")),
    ]
    rows = [f"{tex_escape(k)} & \\multicolumn{{2}}{{l}}{{{tex_escape(v)}}} \\\\" for k, v in tools]
    rows.append(r"\midrule")
    for name in PACKAGES:
        a, b = report.get(name, "--"), eda.get(name, "--")
        mark = r"\,$^{*}$" if "--" not in (a, b) and a != b else ""
        rows.append(f"\\texttt{{{name}}}{mark} & {a} & {b} \\\\")
    toolchain = longtable("@{}lll@{}", ["Component", "report", "eda"], rows,
                          "Toolchain and the versions of the packages that compute or typeset a number, as the lock "
                          "files resolve them on the platform this copy was built on. An asterisk marks a package whose "
                          "versions differ between the environments.", "app-software")  # fmt: skip

    proto = protocol.load()
    data_rows = [f"\\nolinkurl{{data/{name}}} & \\texttt{{{digest[:16]}}} \\\\"
                 for name, digest in sorted(proto["dataset"]["sha256"].items())]  # fmt: skip
    data = longtable("@{}ll@{}", ["File", "SHA-256 (first characters)"], data_rows,
                     "The data files the protocol pins; every claim computed from one of them records the same digest.",
                     "app-data")  # fmt: skip

    in_force = _git("log", "-1", "--format=%h", "--", "report/conf/protocol.toml")
    head = _git("rev-parse", "--short", "HEAD")
    dirty = " with uncommitted changes" if _git("status", "--porcelain", "--", "report") else ""
    prov = [
        ("Protocol frozen at commit", proto["protocol"]["freeze_commit"][:7]),
        ("Protocol in force (last amendment)", in_force),
        ("Report built from commit", head + dirty),
    ]
    prov_rows = [f"{tex_escape(k)} & \\texttt{{{tex_escape(v)}}} \\\\" for k, v in prov]
    provenance = longtable("@{}ll@{}", ["Record", "Value"], prov_rows, "Provenance of this build.",
                           "app-provenance")  # fmt: skip
    return {
        "software-toolchain": toolchain,
        "software-data": data,
        "software-provenance": provenance,
    }


def render_all(claims: dict[str, Claim], out_dir: Path = GENERATED) -> list[Path]:
    target = out_dir / "appendices"
    target.mkdir(parents=True, exist_ok=True)
    per_country(out_dir=out_dir)
    written = []
    fragments = {"traceability": traceability(), "claims": claims_ledger(claims), **software()}
    for name, text in fragments.items():
        path = target / f"{name}.tex"
        path.write_text(f"% Generated by report_lib.appendix. Do not edit.\n{text}")
        written.append(path)
    return written
