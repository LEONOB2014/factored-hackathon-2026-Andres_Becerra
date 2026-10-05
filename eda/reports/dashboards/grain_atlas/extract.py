"""Split the Data Atlas page into reusable modules (header, intro, h2 subsections) plus its JS."""

import re
from pathlib import Path

D = Path(__file__).parent
SRC = D / "data_atlas.html"


def extract():
    s = SRC.read_text()
    mods = {}
    for m in re.finditer(
        r'<section class="view" data-view="([^"]+)"[^>]*>(.*?)</section>', s, re.S
    ):
        vid, body = m.group(1), m.group(2)
        hm = re.search(
            r'<div class="vhead"><div class="eyebrow">(.*?)</div>\s*<h1>(.*?)</h1>\s*(?:<p class="lede">(.*?)</p>)?\s*</div>',
            body,
            re.S,
        )
        if hm:
            eyebrow, title, lede = hm.group(1), hm.group(2), hm.group(3) or ""
            rest = body[hm.end() :]
        else:
            hm2 = re.search(
                r'<div class="vhead">\s*<div class="eyebrow">(.*?)</div>\s*<h1>(.*?)</h1>\s*<p class="lede">(.*?)</p>\s*</div>',
                body,
                re.S,
            )
            eyebrow, title, lede = hm2.group(1), hm2.group(2), hm2.group(3)
            rest = body[hm2.end() :]
        rest = (
            rest.replace("<h3", "<h4")
            .replace("</h3>", "</h4>")
            .replace("<h2>", "<h3>")
            .replace("<h2 ", "<h3 ")
            .replace("</h2>", "</h3>")
        )
        parts = re.split(r"(?=<h3>)", rest)
        intro, subs = parts[0], []
        for p in parts[1:]:
            t = re.match(r"<h3>(.*?)</h3>", p, re.S).group(1)
            subs.append({"t": re.sub(r"<[^>]+>", "", t), "h": p})
        mods[vid] = {
            "eyebrow": eyebrow,
            "title": title,
            "lede": lede.strip(),
            "intro": intro.strip(),
            "subs": subs,
        }
    # JS: helpers + data + renderers (without routing, decision board)
    js = s[
        s.index("/* ---------------- chart helpers") : s.index("/* ---------------- decision board")
    ]
    js = js.replace("const renderers={", "const ATLAS_R={", 1)
    dec = s[s.index("const DECISIONS=[") : s.index("let dbH=null")]
    return mods, js, dec


if __name__ == "__main__":
    mods, js, dec = extract()
    for k, v in mods.items():
        print(
            k,
            "|",
            v["title"][:60],
            "| intro",
            len(v["intro"]),
            "|",
            [x["t"][:40] for x in v["subs"]],
        )
    print(len(js), len(dec))
