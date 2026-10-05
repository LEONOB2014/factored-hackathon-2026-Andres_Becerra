"""Draw the gold star schemas (core facts and use-case marts) as SVG from the built lakehouse.

Each diagram puts the fact or mart in the centre and its dimensions on a ring around it, as in the Kimball
literature. Relationships come from key-column names (KEYS below), columns and row counts from the built relations,
so the pictures follow the models. A dimension is *conformed* when two or more core facts share it.

    cd platform && uv run python dbt/scripts/star_schemas.py    # writes docs/assets/star-schemas/*.svg

The lakehouse path comes from LATAM_DUCKDB_PATH (default <repo>/data/lake/lakehouse.duckdb).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs" / "assets" / "star-schemas"

FACTS = [
    "fct_transaction",
    "fct_complaint",
    "fct_interaction",
    "fct_campaign_send",
    "fct_digital_session",
]
DIMS = [
    "dim_customer",
    "dim_product",
    "dim_date",
    "dim_country",
    "dim_branch",
    "dim_agent",
    "dim_campaign",
    "dim_merchant",
]
MARTS = [
    "mart_card_support",
    "mart_customer_360",
    "mart_account_payment_inquiry",
    "mart_product_recent_transactions",
    "mart_transaction_disputes",
    "mart_credit_eligibility",
    "mart_collections_early_warning",
    "mart_aml_customer_month",
    "mart_cx_journey",
    "mart_campaign_compliance_uplift",
]

# Primary key (first) and business key of each core table.
PK = {
    "dim_customer": ["customer_sk", "customer_id"],
    "dim_product": ["product_sk", "product_id"],
    "dim_date": ["date_key"],
    "dim_country": ["country_code"],
    "dim_branch": ["branch_id"],
    "dim_agent": ["agent_id"],
    "dim_campaign": ["campaign_id"],
    "dim_merchant": ["merchant_id"],
    "fct_transaction": ["transaction_id"],
    "fct_complaint": ["complaint_id"],
    "fct_interaction": ["interaction_id"],
    "fct_campaign_send": ["send_id"],
    "fct_digital_session": ["session_id"],
}

# Foreign-key column name -> the table it joins to.
KEYS = {
    "customer_sk": "dim_customer",
    "customer_id": "dim_customer",
    "product_sk": "dim_product",
    "product_id": "dim_product",
    "affected_product_id": "dim_product",
    "date_key": "dim_date",
    "month_start": "dim_date",
    "snapshot_date": "dim_date",
    "country_code": "dim_country",
    "customer_country_code": "dim_country",
    "transaction_country_code": "dim_country",
    "ip_country_code": "dim_country",
    "branch_id": "dim_branch",
    "related_branch_id": "dim_branch",
    "agent_id": "dim_agent",
    "assigned_agent_id": "dim_agent",
    "campaign_id": "dim_campaign",
    "merchant_id": "dim_merchant",
    "transaction_id": "fct_transaction",
    "linked_transaction_id": "fct_transaction",
    "complaint_id": "fct_complaint",
    "interaction_id": "fct_interaction",
    "origin_interaction_id": "fct_interaction",
    "send_id": "fct_campaign_send",
}

# Keys that exist but must not be used for joins (rule catalog).
DO_NOT_JOIN = {("fct_complaint", "affected_product_id"): "R25: not the customer's product"}

GRAIN = {
    "fct_transaction": "one row per transaction",
    "fct_complaint": "one row per complaint case",
    "fct_interaction": "one row per contact-centre contact",
    "fct_campaign_send": "one row per campaign send",
    "fct_digital_session": "one row per app or web session",
    "mart_card_support": "one row per card",
    "mart_customer_360": "one row per customer",
    "mart_account_payment_inquiry": "one row per product",
    "mart_product_recent_transactions": "last 20 transactions per product",
    "mart_transaction_disputes": "one row per transaction or fee dispute",
    "mart_credit_eligibility": "latest eligibility per customer",
    "mart_collections_early_warning": "one row per loan or credit card",
    "mart_aml_customer_month": "one row per customer and month",
    "mart_cx_journey": "one row per contact",
    "mart_campaign_compliance_uplift": "one row per campaign send",
}
GRAIN_KEYS = {
    "mart_card_support": ["product_id"],
    "mart_customer_360": ["customer_id"],
    "mart_account_payment_inquiry": ["product_id"],
    "mart_product_recent_transactions": ["product_id", "recency_rank"],
    "mart_transaction_disputes": ["complaint_id"],
    "mart_credit_eligibility": ["customer_id"],
    "mart_collections_early_warning": ["product_id"],
    "mart_aml_customer_month": ["customer_id", "month_start"],
    "mart_cx_journey": ["interaction_id"],
    "mart_campaign_compliance_uplift": ["send_id"],
}

# Thin palette: header fill, body fill, stroke.
PALETTE = {
    "fact": ("#FDE68A", "#FFFBEB", "#D97706"),
    "dimension": ("#BAE6FD", "#F0F9FF", "#0284C7"),
    "conformed": ("#E5E7EB", "#F9FAFB", "#6B7280"),
    "mart": ("#DDD6FE", "#F5F3FF", "#7C3AED"),
}
LABEL = {
    "fact": "Fact",
    "dimension": "Dimension",
    "conformed": "Conformed dimension (shared by 2+ facts)",
    "mart": "Use-case mart",
}
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
CHAR = 7.2  # width of one 12 px monospace character
ROW = 17
HEAD = 40


@dataclass
class Box:
    name: str
    kind: str
    rows: list[tuple[str, str]]  # (tag, column)
    subtitle: str
    x: float = 0.0
    y: float = 0.0
    w: float = field(init=False)
    h: float = field(init=False)

    def __post_init__(self) -> None:
        longest = max(
            [len(self.name) * 1.08, len(self.subtitle) * 0.9] + [len(c) + 5 for _, c in self.rows]
        )
        self.w = max(170.0, longest * CHAR + 24)
        self.h = HEAD + ROW * len(self.rows) + 10

    def svg(self) -> str:
        head, body, stroke = PALETTE[self.kind]
        x0, y0 = self.x - self.w / 2, self.y - self.h / 2
        out = [
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{self.w:.1f}" height="{self.h:.1f}" rx="8" '
            f'fill="{body}" stroke="{stroke}" stroke-width="1.2"/>',
            f'<path d="M{x0:.1f},{y0 + HEAD:.1f} v{-HEAD + 8} a8,8 0 0 1 8,-8 h{self.w - 16:.1f} a8,8 0 0 1 8,8 '
            f'v{HEAD - 8}z" fill="{head}" stroke="{stroke}" stroke-width="1.2"/>',
            f'<text x="{x0 + 12:.1f}" y="{y0 + 18:.1f}" font-size="13" font-weight="700" fill="#111827">'
            f"{escape(self.name)}</text>",
            f'<text x="{x0 + 12:.1f}" y="{y0 + 33:.1f}" font-size="10.5" fill="#374151">{escape(self.subtitle)}</text>',
        ]
        for i, (tag, col) in enumerate(self.rows):
            ty = y0 + HEAD + 15 + i * ROW
            colour = {"PK": stroke, "FK": "#475569"}.get(tag, "#6B7280")
            weight = "700" if tag == "PK" else "400"
            out.append(
                f'<text x="{x0 + 12:.1f}" y="{ty:.1f}" font-size="9.5" font-weight="700" fill="{colour}">{tag}</text>'
            )
            out.append(
                f'<text x="{x0 + 40:.1f}" y="{ty:.1f}" font-size="12" font-weight="{weight}" fill="#1F2937">'
                f"{escape(col)}</text>"
            )
        return "\n".join(out)

    def border(self, dx: float, dy: float) -> tuple[float, float]:
        """Point where a ray from the centre in direction (dx, dy) leaves the box."""
        t = min(
            (self.w / 2) / abs(dx) if dx else math.inf,
            (self.h / 2) / abs(dy) if dy else math.inf,
        )
        return self.x + dx * t, self.y + dy * t


def fmt_rows(n: int) -> str:
    return f"{n:,} rows"


class Lakehouse:
    def __init__(self) -> None:
        path = os.environ.get("LATAM_DUCKDB_PATH", str(REPO / "data" / "lake" / "lakehouse.duckdb"))
        con = duckdb.connect(path, read_only=True)
        self.columns: dict[str, list[str]] = {}
        self.count: dict[str, int] = {}
        for table in FACTS + DIMS + MARTS:
            self.columns[table] = [r[0] for r in con.sql(f"describe gold.{table}").fetchall()]
            row = con.sql(f"select count(*) from gold.{table}").fetchone()
            self.count[table] = int(row[0]) if row else 0
        con.close()

    def links(self, table: str) -> dict[str, list[str]]:
        """Target table -> the key columns of `table` that join to it."""
        out: dict[str, list[str]] = {}
        for col in self.columns[table]:
            target = KEYS.get(col)
            if target and target != table:
                out.setdefault(target, []).append(col)
        return out


def conformed_dims(lake: Lakehouse) -> set[str]:
    users: dict[str, int] = {}
    for fact in FACTS:
        for target in lake.links(fact):
            if target.startswith("dim_"):
                users[target] = users.get(target, 0) + 1
    return {d for d, n in users.items() if n >= 2}


def kind_of(table: str, conformed: set[str]) -> str:
    if table.startswith("fct_"):
        return "fact"
    if table.startswith("mart_"):
        return "mart"
    return "conformed" if table in conformed else "dimension"


def satellite(lake: Lakehouse, table: str, conformed: set[str], max_attrs: int = 4) -> Box:
    keys = PK[table]
    rows = [("PK", keys[0])] + [("BK", k) for k in keys[1:]]
    attrs = [c for c in lake.columns[table] if c not in keys and c not in KEYS]
    rows += [("", c) for c in attrs[:max_attrs]]
    if len(attrs) > max_attrs:
        rows.append(("", f"+{len(attrs) - max_attrs} more"))
    return Box(table, kind_of(table, conformed), rows, fmt_rows(lake.count[table]))


def centre(lake: Lakehouse, table: str, conformed: set[str], max_rows: int = 16) -> Box:
    cols = lake.columns[table]
    pk = GRAIN_KEYS.get(table) or PK[table][:1]
    fks = [c for c in cols if c in KEYS and c not in pk]
    rest = [c for c in cols if c not in pk and c not in fks]
    rows = [("PK", c) for c in pk] + [("FK", c) for c in fks]
    room = max(3, max_rows - len(rows))
    rows += [("", c) for c in rest[:room]]
    if len(rest) > room:
        rows.append(("", f"+{len(rest) - room} more columns"))
    subtitle = f"{GRAIN[table]} · {fmt_rows(lake.count[table])}"
    return Box(table, kind_of(table, conformed), rows, subtitle)


def edge(a: Box, b: Box, label: str, many: str, one: str, dashed: bool = False) -> tuple[str, str]:
    """The line (drawn under the boxes) and its labels (drawn over them)."""
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    ax, ay = a.border(ux, uy)
    bx, by = b.border(-ux, -uy)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    colour = "#DC2626" if dashed else "#94A3B8"
    mx, my = (ax + bx) / 2, (ay + by) / 2
    halo = 'stroke="#FFFFFF" stroke-width="4" paint-order="stroke" stroke-linejoin="round"'
    line = f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="{colour}" stroke-width="1.3"{dash}/>'
    lines = label.split("\n")
    labels = [
        f'<text x="{ax + ux * 14:.1f}" y="{ay + uy * 14 + 4:.1f}" font-size="11" font-weight="700" '
        f'text-anchor="middle" fill="#475569" {halo}>{many}</text>',
        f'<text x="{bx - ux * 14:.1f}" y="{by - uy * 14 + 4:.1f}" font-size="11" font-weight="700" '
        f'text-anchor="middle" fill="#475569" {halo}>{one}</text>',
    ]
    for i, text in enumerate(lines):
        y = my + 4 + (i - (len(lines) - 1) / 2) * 13
        labels.append(
            f'<text x="{mx:.1f}" y="{y:.1f}" font-size="10.5" text-anchor="middle" fill="{colour}" {halo}>'
            f"{escape(text)}</text>"
        )
    return line, "\n".join(labels)


def legend(x: float, y: float, kinds: list[str]) -> str:
    out = []
    for i, kind in enumerate(kinds):
        head, body, stroke = PALETTE[kind]
        yy = y + i * 20
        out.append(
            f'<rect x="{x:.1f}" y="{yy:.1f}" width="22" height="13" rx="3" fill="{head}" stroke="{stroke}" '
            f'stroke-width="1.2"/>'
        )
        out.append(
            f'<text x="{x + 30:.1f}" y="{yy + 11:.1f}" font-size="11" fill="#374151">{LABEL[kind]}</text>'
        )
    yy = y + len(kinds) * 20
    out.append(
        f'<line x1="{x:.1f}" y1="{yy + 7:.1f}" x2="{x + 22:.1f}" y2="{yy + 7:.1f}" stroke="#94A3B8"/>'
    )
    out.append(
        f'<text x="{x + 30:.1f}" y="{yy + 11:.1f}" font-size="11" fill="#374151">N · 1: many rows to one; '
        f"label = join key(s)</text>"
    )
    return "\n".join(out)


def document(
    boxes: list[Box], body: list[str], title: str, kinds: list[str], over: list[str] | None = None
) -> str:
    pad = 30
    x0 = min(b.x - b.w / 2 for b in boxes) - pad
    x1 = max(b.x + b.w / 2 for b in boxes) + pad
    y0 = min(b.y - b.h / 2 for b in boxes) - pad - 34
    y1 = max(b.y + b.h / 2 for b in boxes) + pad + 20 * (len(kinds) + 1) + 10
    width = max(x1 - x0, 760)
    x1 = x0 + width
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}" '
        f'width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" font-family="{FONT}">',
        f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" rx="14" fill="#FFFFFF"/>',
        f'<text x="{x0 + pad:.0f}" y="{y0 + 30:.0f}" font-size="15" font-weight="700" fill="#111827">'
        f"{escape(title)}</text>",
        *body,
        *(b.svg() for b in boxes),
        *(over or []),
        legend(x0 + pad, y1 - pad - 20 * (len(kinds) + 1) + 6, kinds),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def star(lake: Lakehouse, table: str, conformed: set[str]) -> str:
    hub = centre(lake, table, conformed)
    links = lake.links(table)
    order = sorted(links, key=lambda t: (not t.startswith("dim_"), (DIMS + FACTS).index(t)))
    sats = [satellite(lake, t, conformed) for t in order]
    n = len(sats)
    rx = hub.w / 2 + max((s.w for s in sats), default=0) / 2 + 240
    ry = hub.h / 2 + max((s.h for s in sats), default=0) / 2 + 70
    body, over = [], []
    for i, sat in enumerate(sats):
        angle = -math.pi / 2 + 2 * math.pi * i / n + (math.pi / n if n == 2 else 0)
        sat.x, sat.y = rx * math.cos(angle), ry * math.sin(angle)
        cols = links[sat.name]
        grain_join = set(cols) <= set(GRAIN_KEYS.get(table) or PK.get(table, [])[:1])
        dashed = any((table, c) in DO_NOT_JOIN for c in cols)
        label = "\n".join(cols) + ("\ndo not join (R25)" if dashed else "")
        line, labels = edge(hub, sat, label, "1" if grain_join else "N", "1", dashed)
        body.append(line)
        over.append(labels)
    kinds = [
        k
        for k in ("mart", "fact", "dimension", "conformed")
        if any(b.kind == k for b in [hub, *sats])
    ]
    title = f"{'Mart' if table.startswith('mart_') else 'Star schema'} · {table}"
    return document([hub, *sats], body, title, kinds, over)


def spread(boxes: list[Box], gap: float) -> None:
    """Keep the boxes in x order, at least `gap` apart between edges, centred on their preferred positions."""
    boxes.sort(key=lambda b: b.x)
    preferred = sum(b.x for b in boxes) / len(boxes)
    for left, right in zip(boxes, boxes[1:], strict=False):
        right.x = max(right.x, left.x + left.w / 2 + gap + right.w / 2)
    shift = preferred - sum(b.x for b in boxes) / len(boxes)
    for box in boxes:
        box.x += shift


def constellation(lake: Lakehouse, conformed: set[str]) -> str:
    """The Kimball fact constellation: facts in the middle row, the dimensions they share above and below."""
    order = [
        "fct_digital_session",
        "fct_transaction",
        "fct_complaint",
        "fct_interaction",
        "fct_campaign_send",
    ]
    facts = [
        Box(
            f,
            "fact",
            [("PK", PK[f][0])],
            f"{GRAIN[f]} · {fmt_rows(lake.count[f])}".replace("one row per ", "per "),
        )
        for f in order
    ]
    x = 0.0
    for f in facts:
        f.x, f.y = x + f.w / 2, 0.0
        x += f.w + 70
    links = {f.name: lake.links(f.name) for f in facts}
    users = {d: [f for f in facts if d in links[f.name]] for d in DIMS}
    top = [d for d in DIMS if len(users[d]) > 2 or d == "dim_product"]
    rows = {"top": [], "bottom": []}
    for d in DIMS:
        box = Box(d, kind_of(d, conformed), [("PK", PK[d][0])], fmt_rows(lake.count[d]))
        box.x = sum(f.x for f in users[d]) / max(len(users[d]), 1)
        box.y = -300.0 if d in top else 300.0
        rows["top" if d in top else "bottom"].append(box)
    for boxes in rows.values():
        spread(boxes, 60)
    dims = rows["top"] + rows["bottom"]
    every = facts + dims
    body = []
    for f in facts:
        for target, cols in links[f.name].items():
            other = next(b for b in every if b.name == target)
            dashed = any((f.name, c) in DO_NOT_JOIN for c in cols)
            stroke = "#DC2626" if dashed else PALETTE[other.kind][2]
            dash = ' stroke-dasharray="5 4"' if dashed else ""
            dx, dy = other.x - f.x, other.y - f.y
            norm = math.hypot(dx, dy) or 1.0
            ax, ay = f.border(dx / norm, dy / norm)
            bx, by = other.border(-dx / norm, -dy / norm)
            body.append(
                f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="{stroke}" '
                f'stroke-opacity="0.55" stroke-width="1.3"{dash}/>'
            )
    title = "Gold core · fact constellation: 5 facts sharing 8 dimensions"
    return document(every, body, title, ["fact", "dimension", "conformed"])


def main() -> None:
    lake = Lakehouse()
    conformed = conformed_dims(lake)
    OUT.mkdir(parents=True, exist_ok=True)
    written = {"gold_core_constellation.svg": constellation(lake, conformed)}
    for table in FACTS + MARTS:
        written[f"{table}.svg"] = star(lake, table, conformed)
    for name, svg in written.items():
        (OUT / name).write_text(svg)
    print(
        f"wrote {len(written)} diagrams to {OUT.relative_to(REPO)}; conformed: {sorted(conformed)}"
    )


if __name__ == "__main__":
    main()
