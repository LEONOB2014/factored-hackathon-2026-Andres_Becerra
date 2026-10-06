"""Draw the lakehouse data flow by grain and country as an animated SVG.

Four grain flows (atomic, day, cell, hour) start from the same lossless bronze records. At the silver boundary each
flow opens into the three country scopes (ADR-016), so silver and gold run as 12 lanes: 4 grains x 3 countries. Every
gold cell has its own readiness gate (ADR-018) and feeds the marts of its grain family (ADR-017). Producers, monitors
and the reasons for the split are drawn around the lanes.

    python scripts/diagrams/granularity_flow.py    # writes docs/assets/architecture/beta-aid-granularity-flow.svg
"""

from __future__ import annotations

from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "assets" / "architecture" / "beta-aid-granularity-flow.svg"
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
W, H = 1800, 1180

COUNTRY = {"MX": "#0D9488", "CO": "#2563EB", "AR": "#EA580C"}
ZONE = {
    "bronze": ("#B7793F", "#FBF3EA"),
    "silver": ("#64748B", "#F5F7FA"),
    "gold": ("#B88A00", "#FFFBEB"),
    "marts": ("#7C3AED", "#F5F3FF"),
    "use": ("#0F172A", "#F8FAFC"),
}
GRAINS = [
    (
        "Event",
        "as delivered: one row per source record",
        "card support · disputes · customer 360 · eligibility",
    ),
    (
        "Day",
        "day and month: series I",
        "market-day · channel-day · branch-day · customer-month (AML)",
    ),
    (
        "Cell",
        "market-hour, campaign cells: series II",
        "campaign decision cell · market-hour monitor",
    ),
    (
        "Hour",
        "each delivery clock: series III",
        "declared clocks · case clock · streaming monitors",
    ),
]
BAND_Y, BAND_H, BAND_GAP = 150, 176, 16
LANE_H, LANE_GAP = 46, 8


def text(x, y, s, size=12, weight=400, fill="#0F172A", anchor="start"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}">{escape(s)}</text>'
    )


def box(x, y, w, h, stroke, fill, rx=10, dash=False, sw=1.3):
    d = ' stroke-dasharray="6 4"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def flow(points, colour):
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<path class="f" d="{d}" stroke="{colour}" marker-end="url(#a{colour[1:]})"/>'


def band_top(k):
    return BAND_Y + k * (BAND_H + BAND_GAP)


def lane_y(k, j):
    return band_top(k) + 10 + j * (LANE_H + LANE_GAP)


def build() -> str:
    out = []
    # producers
    out.append(box(20, 130, 220, 785, "#94A3B8", "#F8FAFC"))
    out.append(text(34, 152, "Producer systems", 13, 700))
    out.append(text(34, 170, "one per country, own distributions", 11, 400, "#64748B"))
    for i, (c, colour) in enumerate(COUNTRY.items()):
        y = 200 + i * 220
        out.append(box(36, y, 188, 150, colour, "#FFFFFF"))
        out.append(f'<rect x="36" y="{y}" width="8" height="150" rx="4" fill="{colour}"/>')
        name = {"MX": "Mexico", "CO": "Colombia", "AR": "Argentina"}[c]
        out.append(text(56, y + 28, f"{c} · {name}", 14, 700, colour))
        for n, line in enumerate(
            [
                "core banking, cards, CRM",
                "own nulls, codes, clocks",
                "own schema versions",
                "own currency, ticket sizes",
            ]
        ):
            out.append(text(56, y + 54 + n * 22, line, 11.5, 400, "#475569"))
    # bronze
    bs, bf = ZONE["bronze"]
    out.append(box(262, 130, 236, 785, bs, bf))
    out.append(text(276, 152, "Landing → bronze_raw", 13, 700, "#7C4A1E"))
    out.append(text(276, 170, "lossless · fingerprinted · lineage", 11, 400, "#7C4A1E"))
    for k, (g, sub, _) in enumerate(GRAINS):
        y = band_top(k)
        out.append(box(274, y + 30, 212, BAND_H - 40, bs, "#FFFFFF", rx=8))
        out.append(text(288, y + 58, f"{g} flow", 15, 700, "#7C4A1E"))
        words = sub.split(": ") if ": " in sub else [sub]
        out.append(text(288, y + 80, words[0], 11, 400, "#475569"))
        if len(words) > 1:
            out.append(text(288, y + 96, words[1], 11, 400, "#475569"))
        out.append(text(288, y + BAND_H - 24, "from the same event records", 10.5, 400, "#94A3B8"))
    # country cut gate
    out.append(
        '<rect x="512" y="130" width="16" height="785" rx="8" fill="#FFF7ED" stroke="#F59E0B" stroke-width="1.2"/>'
    )
    out.append(text(520, 104, "country scope cut · ADR-016", 11.5, 700, "#B45309", "middle"))
    out.append(text(520, 120, "+ ALL pooled scope, for comparison", 11, 400, "#B45309", "middle"))
    # silver and gold lanes
    ss, sf = ZONE["silver"]
    gs, gf = ZONE["gold"]
    out.append(box(542, 130, 470, 785, ss, sf))
    out.append(text(556, 152, "Silver · per country", 13, 700, "#334155"))
    out.append(
        text(
            556,
            170,
            "typed contract → quality rules R01–R27 → conformed (FX, clocks)",
            11,
            400,
            "#475569",
        )
    )
    out.append(box(1030, 130, 330, 785, gs, gf))
    out.append(text(1044, 152, "Gold · 12 cells = 4 grains × 3 countries", 13, 700, "#7A5B00"))
    out.append(text(1044, 170, "Kimball star + readiness gate per cell", 11, 400, "#7A5B00"))
    flows = []
    for k, (g, _, _) in enumerate(GRAINS):
        for j, (c, colour) in enumerate(COUNTRY.items()):
            y = lane_y(k, j) + 26
            ly = lane_y(k, j) + 26
            # silver lane
            out.append(box(556, ly - 4, 442, LANE_H - 6, colour, "#FFFFFF", rx=7))
            out.append(
                f'<rect x="556" y="{ly - 4}" width="44" height="{LANE_H - 6}" rx="7" fill="{colour}"/>'
            )
            out.append(text(578, ly + 21, c, 13, 700, "#FFFFFF", "middle"))
            out.append(
                text(
                    612,
                    ly + 14,
                    f"{g.lower()} · contract, drift baseline, imputation",
                    11,
                    600,
                    "#334155",
                )
            )
            out.append(
                text(
                    612, ly + 30, "estimated on this country's own population", 10.5, 400, "#64748B"
                )
            )
            # gold cell
            out.append(box(1044, ly - 4, 302, LANE_H - 6, colour, "#FFFFFF", rx=7))
            out.append(text(1058, ly + 14, f"{c} · {g.lower()} star", 12, 700, colour))
            out.append(text(1058, ly + 30, "grain · reconcile · dense tests", 10.5, 400, "#64748B"))
            out.append(
                f'<circle cx="1322" cy="{ly + 17}" r="11" fill="#FFFFFF" stroke="#B45309" stroke-width="1.6"/>'
            )
            out.append(text(1322, ly + 21, "G", 11, 700, "#B45309", "middle"))
            # flows: bronze band -> cut -> silver lane -> gold cell
            flows.append(
                flow(
                    [
                        (486, band_top(k) + BAND_H / 2),
                        (520, band_top(k) + BAND_H / 2),
                        (520, ly + 17),
                        (552, ly + 17),
                    ],
                    colour,
                )
            )
            flows.append(flow([(998, ly + 17), (1040, ly + 17)], colour))
            flows.append(flow([(1334, ly + 17), (1384, band_top(k) + BAND_H / 2)], colour))
        y0 = band_top(k)
        out.append(text(1006, y0 + 4, "", 1))
    # marts per grain family
    ms, mf = ZONE["marts"]
    out.append(box(1380, 130, 200, 785, ms, mf))
    out.append(text(1394, 152, "Marts per grain family", 13, 700, "#5B21B6"))
    out.append(text(1394, 170, "derived from each gold cell", 11, 400, "#5B21B6"))
    for k, (g, _, marts) in enumerate(GRAINS):
        y = band_top(k)
        out.append(box(1392, y + 30, 176, BAND_H - 40, ms, "#FFFFFF", rx=8))
        out.append(text(1404, y + 54, f"{g} marts", 13, 700, "#5B21B6"))
        for n, part in enumerate(marts.split(" · ")):
            out.append(text(1404, y + 76 + n * 18, part, 11, 400, "#475569"))
        flows.append(flow([(1568, y + BAND_H / 2), (1604, y + BAND_H / 2)], "#7C3AED"))
    # consumers
    us, uf = ZONE["use"]
    out.append(box(1606, 130, 174, 785, "#94A3B8", "#F8FAFC"))
    out.append(text(1620, 152, "Products, decisions", 13, 700))
    out.append(text(1620, 170, "per country, per grain", 11, 400, "#64748B"))
    uses = [
        ("Card copilot", "first product off the line"),
        ("Disputes, collections", "next green gates"),
        ("AML monitoring", "customer-month typologies"),
        ("Campaign decisions", "cells with consent check"),
        ("Data-office scorecard", "12 gate verdicts → data"),
        ("", "requirements with owners"),
    ]
    yy = 200
    for title, sub in uses:
        if title:
            out.append(box(1618, yy, 150, 92, "#CBD5E1", "#FFFFFF", rx=8))
            out.append(text(1630, yy + 28, title, 12, 700))
            out.append(text(1630, yy + 48, sub, 10.5, 400, "#64748B"))
            yy += 108
        else:
            out.append(text(1630, yy - 108 + 66, sub, 10.5, 400, "#64748B"))
    # producers -> bronze
    for i, colour in enumerate(COUNTRY.values()):
        flows.append(flow([(224, 275 + i * 220), (258, 275 + i * 220)], colour))
    # monitors strip
    out.append(box(20, 935, 1760, 80, "#B45309", "#FFFDF8", dash=True))
    out.append(
        text(
            36,
            961,
            "Watched per producer × country × grain (the consumer receives many producers)",
            13,
            700,
            "#92400E",
        )
    )
    mon = [
        "Audit: hash-chained ledger of every load and correction",
        "Anomalies: DQ rule rates R01–R27 per country, with SLOs",
        "Drift: PSI against each country's own reference window",
        "Schema evolution: circuit breaker per source contract",
    ]
    for i, m in enumerate(mon):
        out.append(text(36 + i * 440, 991, "■ " + m, 11.5, 400, "#334155"))
    # why cards
    why = [
        (
            "Producers differ",
            "Each country's systems send their own distributions, nulls, codes and schema versions. Contracts, drift baselines and imputations are estimated per country, so one market never hides another.",
        ),
        (
            "Pooled data can hide local signal",
            "If P(y | x, country) differs by country, a pooled model learns a blur. Each cell is judged on its own and against the pooled ALL scope. On this synthetic feed the countries behave alike: no hidden signal, a finding in itself.",
        ),
        (
            "The grain decides what is learnable",
            "Per hour the transactions are flat; per day a weekly pulse appears. Twelve gate verdicts (4 grains × 3 countries) turn into data requirements with owners and acceptance tests.",
        ),
    ]
    for i, (title, body) in enumerate(why):
        x = 20 + i * 594
        out.append(box(x, 1035, 572, 125, "#CBD5E1", "#FFFFFF"))
        out.append(text(x + 18, 1063, title, 15, 700))
        line, lines = "", []
        for word in body.split():
            if len(line) + len(word) + 1 > 84:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        for n, ln in enumerate(lines):
            out.append(text(x + 18, 1089 + n * 20, ln, 12, 400, "#475569"))

    colours = sorted({*COUNTRY.values(), "#7C3AED"})
    markers = "".join(
        f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for c in colours
    )
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        "<title>BETA AID lakehouse by grain and country</title>",
        f"<defs>{markers}<style>",
        ".f{fill:none;stroke-width:2;stroke-linejoin:round;stroke-dasharray:7 5;animation:flow 1.1s linear infinite}",
        "@keyframes flow{to{stroke-dashoffset:-24}}",
        "@media (prefers-reduced-motion: reduce){.f{animation:none}}",
        "</style></defs>",
        f'<rect width="{W}" height="{H}" rx="16" fill="#FFFFFF"/>',
        text(24, 40, "BETA AID · the lakehouse by grain and country", 20, 800),
        text(24, 62, "Andrés Becerra", 14, 700, "#334155"),
        text(
            24,
            81,
            "4 grain flows from lossless bronze, opened per country at silver: 12 gold cells, each with its own readiness gate and marts",
            11.5,
            400,
            "#64748B",
        ),
    ]
    return "\n".join([*head, *out, *flows, "</svg>"]) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
