"""Generate the three country series from one template: notebooks/country_template → notebooks/country_{mx,co,ar}.

The template is the only place to edit. Each generated source differs from it in two tokens, the country code
and its name, so the three series cannot drift apart in method; their executed outputs (and the decisions they
compute) differ because the data does.

    uv run scripts/build_country_notebooks.py            # regenerate the .py sources
    for cc in mx co ar; do for nb in notebooks/country_$cc/[0-9][0-9]_*.py; do
        uv run scripts/build_country_notebooks.py --execute "$nb"; done; done
"""

import argparse
from pathlib import Path

import build_notebook

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "notebooks" / "country_template"
NAMES = {"MX": "Mexico", "CO": "Colombia", "AR": "Argentina"}


def render(text: str, code: str) -> str:
    return text.replace("__COUNTRY__", code).replace("__COUNTRY_NAME__", NAMES[code])


def generate() -> list[Path]:
    out = []
    for code in NAMES:
        folder = ROOT / "notebooks" / f"country_{code.lower()}"
        folder.mkdir(exist_ok=True)
        for src in sorted(TEMPLATE.glob("[0-9][0-9]_*.py")):
            dst = folder / src.name
            dst.write_text(render(src.read_text(), code))
            out.append(dst)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--execute", type=Path, help="execute one generated notebook and export its HTML"
    )
    a = ap.parse_args()
    if a.execute:
        src = a.execute.resolve()
        build_notebook.build(
            src, execute=True, html_dir=ROOT / "reports" / "notebooks" / src.parent.name
        )
        return
    for p in generate():
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
