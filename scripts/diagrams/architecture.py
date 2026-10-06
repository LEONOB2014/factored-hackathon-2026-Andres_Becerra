"""Draw the BETA AID infrastructure and data-flow diagram as an animated SVG.

Boundaries follow the deployment: the public internet, the Google Cloud project with one Cloud Run service per
residency region, the Modal demo, and the Docker host of the data platform with its networks exactly as
`platform/docker/compose.yml` declares them (internal networks have no route out; published ports bind to
127.0.0.1). Flow lines are animated dashes, coloured by kind; `prefers-reduced-motion` stops them.

    python scripts/diagrams/architecture.py    # writes docs/assets/architecture/beta-aid-architecture.svg

Logos are Simple Icons (CC0), fetched once per run at a pinned version and inlined.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "assets" / "architecture" / "beta-aid-architecture.svg"
ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@15.22.0/icons/{}.svg"
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
W, H = 1720, 1190
HEADER = 20  # extra room under the title for the author line; the body shifts down by this much

BRAND = {
    "apacheairflow": "#017CEE",
    "dbt": "#FF694B",
    "duckdb": "#1A1A1A",
    "postgresql": "#4169E1",
    "neo4j": "#4581C3",
    "mlflow": "#0194E2",
    "apacheflink": "#E6526F",
    "minio": "#C72E49",
    "kong": "#003459",
    "grafana": "#F46800",
    "prometheus": "#E6522C",
    "docker": "#2496ED",
    "googlecloud": "#4285F4",
    "netlify": "#00A49A",
    "fastapi": "#009688",
    "claude": "#D97757",
    "terraform": "#844FBA",
    "githubactions": "#2088FF",
    "github": "#181717",
    "modal": "#3BA55C",
    "optuna": "#3B5BA5",
    "python": "#3776AB",
}

# Generic glyphs (24 x 24) for things without a logo.
GLYPHS = {
    "person": "M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0 2c-4.4 0-9 2.2-9 5.5V22h18v-2.5C21 16.2 16.4 14 12 14Z",
    "stream": "M2 7c3 0 3-3 6-3s3 3 6 3 3-3 6-3v3c-3 0-3 3-6 3s-3-3-6-3-3 3-6 3Zm0 7c3 0 3-3 6-3s3 3 6 3 3-3 6-3v3c-3"
    " 0-3 3-6 3s-3-3-6-3-3 3-6 3Zm0 7c3 0 3-3 6-3s3 3 6 3 3-3 6-3v3c-3 0-3 3-6 3s-3-3-6-3-3 3-6 3Z",
    "lineage": "M5 3a3 3 0 1 1 0 6 3 3 0 0 1 0-6Zm14 0a3 3 0 1 1 0 6 3 3 0 0 1 0-6ZM12 15a3 3 0 1 1 0 6 3 3 0 0 1 "
    "0-6ZM6.5 8.2l4.6 7.1-1.7 1.1-4.6-7.1Zm11 0 1.7 1.1-4.6 7.1-1.7-1.1Z",
    "doc": "M6 2h8l5 5v15H6Zm7 1.5V8h4.5ZM8.5 12h8v1.5h-8Zm0 3.5h8V17h-8Zm0 3.5h5v1.5h-5Z",
    "bucket": "M3 5c0-1.7 4-3 9-3s9 1.3 9 3l-2.2 14.6C18.5 21 15.6 22 12 22s-6.5-1-6.8-2.4ZM12 4C7.9 4 5.3 4.9 5 5.5c.3"
    ".6 2.9 1.5 7 1.5s6.7-.9 7-1.5C18.7 4.9 16.1 4 12 4Z",
    "lock": "M7 10V7a5 5 0 0 1 10 0v3h1.5v12h-13V10Zm2 0h6V7a3 3 0 0 0-6 0Z",
    "globe": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm6.9 6h-3a15 15 0 0 0-1.3-3.9A8 8 0 0 1 18.9 8ZM12 4c.8 1.1 1.5 "
    "2.5 1.9 4h-3.8c.4-1.5 1.1-2.9 1.9-4ZM4.3 14a8 8 0 0 1 0-4h3.4a16 16 0 0 0 0 4Zm.8 2h3a15 15 0 0 0 1.3 3.9A8 8 "
    "0 0 1 5.1 16Zm3-8h-3a8 8 0 0 1 4.3-3.9A15 15 0 0 0 8.1 8ZM12 20c-.8-1.1-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.9-1.9 "
    "4Zm2.3-6H9.7a14 14 0 0 1 0-4h4.6a14 14 0 0 1 0 4Zm.3 5.9A15 15 0 0 0 15.9 16h3a8 8 0 0 1-4.3 3.9Zm1.7-5.9a16 "
    "16 0 0 0 0-4h3.4a8 8 0 0 1 0 4Z",
}
GLYPH_COLOUR = {
    "bucket": "#569A31",
    "person": "#475569",
    "stream": "#E2401B",
    "lineage": "#0F766E",
    "doc": "#475569",
    "lock": "#B45309",
}

FLOW = {
    "customer": ("#16A34A", "customer and agent traffic"),
    "pipeline": ("#2563EB", "data pipeline"),
    "publish": ("#0D9488", "publication and regional snapshot"),
    "stream": ("#EA580C", "streaming"),
    "ml": ("#7C3AED", "ML"),
    "llm": ("#DB2777", "LLM fallback"),
    "control": ("#64748B", "control, audit and lineage"),
}


def fetch_icon(slug: str) -> str:
    with urllib.request.urlopen(ICONS.format(slug), timeout=30) as response:  # noqa: S310 (pinned https CDN)
        svg = response.read().decode()
    match = re.search(r'<path d="([^"]+)"', svg)
    if not match:
        raise ValueError(f"no path in icon {slug}")
    return match.group(1)


class Icons:
    def __init__(self) -> None:
        self.paths: dict[str, str] = {}

    def draw(self, name: str, x: float, y: float, size: float = 24) -> str:
        if name in GLYPHS:
            path, colour = GLYPHS[name], GLYPH_COLOUR.get(name, "#475569")
        else:
            if name not in self.paths:
                self.paths[name] = fetch_icon(name)
            path, colour = self.paths[name], BRAND[name]
        scale = size / 24
        return f'<path transform="translate({x:.1f},{y:.1f}) scale({scale:.3f})" d="{path}" fill="{colour}"/>'


@dataclass
class Node:
    key: str
    x: float
    y: float
    w: float
    title: str
    sub: str
    icon: str
    h: float = 56

    @property
    def left(self) -> float:
        return self.x - self.w / 2

    @property
    def right(self) -> float:
        return self.x + self.w / 2

    @property
    def top(self) -> float:
        return self.y - self.h / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h / 2


def halo(
    x: float, y: float, text: str, colour: str, size: float = 10.5, anchor: str = "middle"
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{colour}" '
        f'stroke="#FFFFFF" stroke-width="4" paint-order="stroke" stroke-linejoin="round">{escape(text)}</text>'
    )


def zone(
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    *,
    style: str,
    icon: str | None,
    icons: Icons,
) -> str:
    """style: cloud (solid, tinted), network (dashed), internal (dashed + lock), band (light)."""
    stroke, fill, dash = {
        "cloud": ("#94A3B8", "#F8FAFC", ""),
        "gcp": ("#4285F4", "#F5F9FF", ""),
        "docker": ("#2496ED", "#F4FAFE", ""),
        "modal": ("#3BA55C", "#F4FBF6", ""),
        "network": ("#94A3B8", "#FFFFFF", ' stroke-dasharray="6 4"'),
        "internal": ("#B45309", "#FFFDF8", ' stroke-dasharray="6 4"'),
        "region": ("#4285F4", "#FFFFFF", ' stroke-dasharray="4 3"'),
        "band": ("#CBD5E1", "#F8FAFC", ""),
    }[style]
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="1.3"{dash}/>'
    ]
    tx = x + 12
    if icon:
        out.append(icons.draw(icon, x + 10, y + 8, 16))
        tx += 22
    if style == "internal":
        out.append(icons.draw("lock", tx - 2, y + 8, 14))
        tx += 18
    out.append(
        f'<text x="{tx}" y="{y + 21}" font-size="11.5" font-weight="700" fill="#334155">{escape(label)}</text>'
    )
    return "\n".join(out)


def node_svg(n: Node, icons: Icons) -> str:
    return "\n".join(
        [
            f'<rect x="{n.left:.1f}" y="{n.top:.1f}" width="{n.w}" height="{n.h}" rx="8" fill="#FFFFFF" '
            f'stroke="#CBD5E1" stroke-width="1.2" filter="url(#shadow)"/>',
            icons.draw(n.icon, n.left + 11, n.y - 13, 26),
            f'<text x="{n.left + 46:.1f}" y="{n.y - 3:.1f}" font-size="12.5" font-weight="700" fill="#0F172A">'
            f"{escape(n.title)}</text>",
            f'<text x="{n.left + 46:.1f}" y="{n.y + 13:.1f}" font-size="10.5" fill="#64748B">{escape(n.sub)}</text>',
        ]
    )


def flow(points: list[tuple[float, float]], kind: str) -> str:
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<path class="f {kind}" d="{d}" marker-end="url(#arrow-{kind})"/>'


def build() -> str:
    icons = Icons()
    nodes = {
        n.key: n
        for n in [
            # public internet
            Node("cardholder", 155, 150, 230, "Card holders", "ES · PT · MX, CO and AR", "person"),
            Node(
                "agents",
                155,
                270,
                230,
                "Agents and supervisors",
                "contact centre, four eyes",
                "person",
            ),
            Node(
                "console",
                155,
                400,
                230,
                "BETA AID Console",
                "Netlify CDN · TanStack Start",
                "netlify",
            ),
            Node(
                "claude",
                155,
                540,
                230,
                "Claude API",
                "only when the intent model is unsure",
                "claude",
            ),
            Node("s3", 155, 880, 230, "Source bucket", "S3 · 13 tables, read-only", "bucket"),
            # google cloud
            Node(
                "runmx",
                470,
                215,
                190,
                "Cloud Run · beta-aid-mx",
                "copilot API and UI",
                "googlecloud",
            ),
            Node(
                "runsa",
                470,
                385,
                190,
                "Cloud Run · beta-aid-sa",
                "copilot API and UI",
                "googlecloud",
            ),
            Node(
                "build", 470, 620, 190, "Cloud Build", "regional buckets · registry", "googlecloud"
            ),
            Node("secrets", 660, 620, 150, "Secret Manager", "session keys", "googlecloud"),
            # modal
            Node(
                "modal",
                470,
                775,
                210,
                "beta-aid-copilot-web",
                "ASGI app · copilot-data volume",
                "modal",
            ),
            # docker host
            Node("kong", 915, 190, 140, "Kong", "API gateway", "kong"),
            Node("redpanda", 1120, 190, 160, "Redpanda", "Kafka API · events", "stream"),
            Node("flink", 1320, 190, 160, "Flink 1.19", "fraud features", "apacheflink"),
            Node("scorer", 1535, 190, 170, "Fraud scorer", "online features", "python"),
            Node("minio", 915, 340, 140, "MinIO", "landing · WORM", "minio"),
            Node("airflow", 915, 470, 140, "Airflow 3.1", "Cosmos · scopes", "apacheairflow"),
            Node("pgcore", 1580, 350, 170, "Postgres 16", "bank_serving · pgvector", "postgresql"),
            Node("neo4j", 1580, 470, 170, "Neo4j 5", "knowledge graph", "neo4j"),
            Node("kb", 1240, 600, 200, "knowledge/*.md", "approved · versioned · in-window", "doc"),
            Node("mlflow", 930, 750, 150, "MLflow", "runs · registry", "mlflow"),
            Node("optuna", 1160, 750, 150, "Optuna", "intent tuning", "optuna"),
            Node(
                "pgaudit",
                1370,
                750,
                180,
                "Postgres · pg-audit",
                "hash-chained ledger",
                "postgresql",
            ),
            Node("worm", 1580, 750, 150, "WORM anchors", "object lock", "minio"),
            Node("marquez", 930, 890, 150, "Marquez", "OpenLineage", "lineage"),
            Node("prometheus", 1130, 890, 150, "Prometheus", "metrics", "prometheus"),
            Node("grafana", 1330, 890, 150, "Grafana", "dashboards", "grafana"),
            # delivery
            Node("github", 150, 1075, 190, "GitHub", "PRs: develop → main", "github"),
            Node(
                "actions",
                420,
                1075,
                230,
                "GitHub Actions",
                "pre-commit · tests · dbt",
                "githubactions",
            ),
            Node("modaldeploy", 720, 1075, 190, "Modal deploy", "make copilot-deploy", "modal"),
            Node(
                "gcpdeploy",
                990,
                1075,
                230,
                "Cloud Build → Cloud Run",
                "make copilot-deploy-gcp",
                "googlecloud",
            ),
            Node("netlifydeploy", 1265, 1075, 180, "Netlify deploy", "console build", "netlify"),
            Node("terraform", 1540, 1075, 200, "Terraform", "GCP modules (designed)", "terraform"),
        ]
    }

    zones = [
        zone(20, 80, 270, 890, "Public internet", style="cloud", icon="globe", icons=icons),
        zone(
            340,
            80,
            410,
            600,
            "Google Cloud · project",
            style="gcp",
            icon="googlecloud",
            icons=icons,
        ),
        zone(
            360,
            130,
            370,
            150,
            "northamerica-south1 · Querétaro",
            style="region",
            icon=None,
            icons=icons,
        ),
        zone(
            360,
            300,
            370,
            150,
            "southamerica-east1 · São Paulo",
            style="region",
            icon=None,
            icons=icons,
        ),
        zone(
            340, 700, 410, 140, "Modal · serverless demo", style="modal", icon="modal", icons=icons
        ),
        zone(
            780,
            80,
            920,
            890,
            "Private data platform · Docker host · ports bound to 127.0.0.1",
            style="docker",
            icon="docker",
            icons=icons,
        ),
        zone(830, 120, 170, 130, "net_edge", style="network", icon=None, icons=icons),
        zone(
            1020, 120, 660, 130, "net_stream · internal", style="internal", icon=None, icons=icons
        ),
        zone(830, 280, 850, 380, "net_data · internal", style="internal", icon=None, icons=icons),
        zone(830, 690, 410, 120, "net_ml · internal", style="internal", icon=None, icons=icons),
        zone(1260, 690, 420, 120, "net_audit · internal", style="internal", icon=None, icons=icons),
        zone(830, 830, 850, 120, "net_ops", style="network", icon=None, icons=icons),
        zone(
            20, 1000, 1680, 150, "Delivery · CI/CD", style="band", icon="githubactions", icons=icons
        ),
    ]

    # The lakehouse container and its zones.
    lake = [
        '<rect x="1020" y="300" width="440" height="200" rx="10" fill="#FFFBEB" stroke="#F59E0B" stroke-width="1.3"/>',
        icons.draw("duckdb", 1032, 309, 18),
        icons.draw("dbt", 1054, 309, 18),
        '<text x="1080" y="323" font-size="12" font-weight="700" fill="#334155">Lakehouse · DuckDB + dbt · '
        "134 models</text>",
    ]
    chips = [
        ("bronze_raw", 1080, "#D6A26B"),
        ("silver", 1185, "#94A3B8"),
        ("gold", 1290, "#EAB308"),
        ("serving", 1395, "#0D9488"),
    ]
    for label, cx, colour in chips:
        lake.append(
            f'<rect x="{cx - 45}" y="373" width="90" height="34" rx="17" fill="#FFFFFF" stroke="{colour}" '
            f'stroke-width="2"/>'
        )
        lake.append(
            f'<text x="{cx}" y="394" font-size="11.5" font-weight="700" text-anchor="middle" fill="#334155">'
            f"{label}</text>"
        )
    lake.append(
        halo(1240, 440, "contracts · quality rules R01–R27 · governance gates", "#64748B", 10.5)
    )
    lake.append(
        halo(
            1240,
            460,
            "SCD2 core · marts · aggregates · features · graph · privacy",
            "#64748B",
            10.5,
        )
    )
    lake.append(halo(1240, 480, "country scopes ALL · MX · CO · AR", "#64748B", 10.5))

    # Gate between the internet and the services.
    gate = [
        '<rect x="308" y="110" width="14" height="750" rx="7" fill="#FFF7ED" stroke="#F59E0B" stroke-width="1.2"/>',
        icons.draw("lock", 306, 118, 18),
        icons.draw("lock", 306, 480, 18),
        icons.draw("lock", 306, 836, 18),
        halo(
            332, 878, "gate: TLS · CORS allow-list · HMAC session + step-up", "#B45309", 10, "start"
        ),
    ]

    flows = [
        # customers and agents
        flow([(270, 150), (315, 150), (315, 205), (375, 205)], "customer"),
        flow([(315, 205), (315, 375), (375, 375)], "customer"),
        flow([(315, 375), (315, 765), (365, 765)], "customer"),
        flow([(155, 298), (155, 372)], "customer"),
        flow([(270, 400), (375, 400)], "customer"),
        flow([(270, 410), (330, 410), (330, 228), (375, 228)], "customer"),
        # LLM fallback
        flow([(470, 413), (470, 540), (270, 540)], "llm"),
        # ingestion and the lakehouse
        flow([(270, 880), (300, 880), (300, 985), (796, 985), (796, 340), (845, 340)], "pipeline"),
        flow([(985, 340), (1003, 340), (1003, 390), (1035, 390)], "pipeline"),
        flow([(1125, 390), (1140, 390)], "pipeline"),
        flow([(1230, 390), (1245, 390)], "pipeline"),
        flow([(1335, 390), (1350, 390)], "pipeline"),
        # publication
        flow([(1440, 390), (1478, 390), (1478, 350), (1495, 350)], "publish"),
        flow([(1340, 590), (1580, 590), (1580, 498)], "publish"),
        flow([(1340, 580), (1468, 580), (1468, 368), (1495, 368)], "publish"),
        flow([(1395, 373), (1395, 265), (765, 265), (765, 215), (565, 215)], "publish"),
        flow([(765, 265), (765, 385), (565, 385)], "publish"),
        flow([(765, 385), (765, 775), (575, 775)], "publish"),
        # streaming
        flow([(1040, 190), (1065, 190)], "stream"),
        flow([(1200, 190), (1240, 190)], "stream"),
        flow([(1400, 190), (1450, 190)], "stream"),
        flow([(1535, 218), (1535, 322)], "stream"),
        flow([(985, 180), (1005, 180), (1005, 112), (1600, 112), (1600, 162)], "stream"),
        # ML
        flow([(1050, 500), (1050, 645), (980, 645), (980, 722)], "ml"),
        flow([(1085, 750), (1005, 750)], "ml"),
        # control, audit and lineage
        flow([(915, 442), (915, 368)], "control"),
        flow([(985, 470), (1020, 470)], "control"),
        flow([(915, 498), (915, 675), (1250, 675), (1250, 750), (1280, 750)], "control"),
        flow([(1620, 190), (1690, 190), (1690, 683), (1430, 683), (1430, 722)], "control"),
        flow([(845, 470), (814, 470), (814, 890), (855, 890)], "control"),
        flow([(1205, 890), (1255, 890)], "control"),
        flow([(1460, 750), (1505, 750)], "control"),
        # delivery
        flow([(245, 1075), (305, 1075)], "control"),
        flow([(535, 1075), (625, 1075)], "control"),
        flow([(420, 1103), (420, 1128), (990, 1128), (990, 1103)], "control"),
        flow([(990, 1128), (1265, 1128), (1265, 1103)], "control"),
    ]

    labels = [
        halo(555, 980, "pull · read-only", FLOW["pipeline"][0]),
        halo(1080, 260, "serving snapshot, cut per region", FLOW["publish"][0]),
        halo(1580, 410, "digest-checked publish", FLOW["publish"][0]),
        halo(1460, 618, "kb_sync: active versions only", FLOW["publish"][0]),
        halo(1300, 108, "scoring API through Kong (net_app)", FLOW["stream"][0]),
        halo(1545, 278, "online_features", FLOW["stream"][0], anchor="start"),
        halo(380, 528, "fallback only, both regions", FLOW["llm"][0], anchor="start"),
        halo(1120, 670, "ledger events", FLOW["control"][0]),
        halo(1560, 679, "decision audit", FLOW["control"][0]),
        halo(808, 640, "lineage", FLOW["control"][0], anchor="end"),
        halo(1015, 640, "features", FLOW["ml"][0]),
        halo(1668, 802, "no published port", "#B45309", 10, "end"),
        halo(715, 148, "other region → 401", "#DC2626", 10, "end"),
        halo(715, 318, "other region → 401", "#DC2626", 10, "end"),
        halo(375, 268, "Artifact Registry · regional build bucket", "#64748B", 10, "start"),
        halo(375, 438, "Artifact Registry · regional build bucket", "#64748B", 10, "start"),
    ]

    legend = []
    lx = 600
    for kind, (_, text) in FLOW.items():
        legend.append(f'<path class="f {kind}" d="M{lx},34 L{lx + 26},34"/>')
        legend.append(
            f'<text x="{lx + 32}" y="38" font-size="11" fill="#334155">{escape(text)}</text>'
        )
        lx += 42 + len(text) * 5.7
    legend.append(
        '<rect x="600" y="50" width="26" height="14" rx="3" fill="#FFFDF8" stroke="#B45309" stroke-dasharray="4 3"/>'
    )
    legend.append(
        '<text x="632" y="61" font-size="11" fill="#334155">internal network: no route out</text>'
    )
    legend.append(
        '<rect x="830" y="50" width="26" height="14" rx="3" fill="#FFFFFF" stroke="#94A3B8" stroke-dasharray="4 3"/>'
    )
    legend.append(
        '<text x="862" y="61" font-size="11" fill="#334155">network with a published edge</text>'
    )
    legend.append(
        '<rect x="1070" y="50" width="14" height="14" rx="7" fill="#FFF7ED" stroke="#F59E0B"/>'
    )
    legend.append('<text x="1092" y="61" font-size="11" fill="#334155">security gate</text>')

    markers = "\n".join(
        f'<marker id="arrow-{kind}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>'
        for kind, (colour, _) in FLOW.items()
    )
    styles = "\n".join(f".{kind}{{stroke:{colour}}}" for kind, (colour, _) in FLOW.items())

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        "<title>BETA AID infrastructure and data flow</title>",
        "<defs>",
        markers,
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="140%">'
        '<feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-color="#0F172A" flood-opacity="0.12"/></filter>',
        "<style>",
        ".f{fill:none;stroke-width:2;stroke-linejoin:round;stroke-dasharray:7 5;animation:flow 1.1s linear infinite}",
        "@keyframes flow{to{stroke-dashoffset:-24}}",
        "@media (prefers-reduced-motion: reduce){.f{animation:none}}",
        styles,
        "</style>",
        "</defs>",
        f'<rect width="{W}" height="{H}" rx="16" fill="#FFFFFF"/>',
        '<text x="24" y="40" font-size="20" font-weight="800" fill="#0F172A">BETA AID · infrastructure and data '
        "flow</text>",
        '<text x="24" y="62" font-size="14" font-weight="700" fill="#334155">Andrés Becerra</text>',
        '<text x="24" y="81" font-size="11.5" fill="#64748B">Banking Evolutionary Transformation and AI Deployment '
        "· Factored AI &amp; Data Hackathon 2026</text>",
        *legend,
        f'<g transform="translate(0,{HEADER})">',
        *zones,
        *lake,
        *gate,
        *flows,
        *(node_svg(n, icons) for n in nodes.values()),
        *labels,
        "</g>",
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
