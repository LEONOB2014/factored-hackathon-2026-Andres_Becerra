"""The master document includes every chapter and appendix, and every file it includes exists."""

import re
from pathlib import Path

TEX = Path(__file__).resolve().parents[1] / "tex"


def test_every_include_exists_and_every_chapter_is_included():
    main = (TEX / "main.tex").read_text()
    included = set(re.findall(r"\\include\{([^}]+)\}", main))
    for name in included:
        assert (TEX / f"{name}.tex").is_file(), name
    on_disk = {
        f"{p.parent.name}/{p.stem}"
        for d in ("chapters", "appendices")
        for p in (TEX / d).glob("*.tex")
    }
    assert on_disk == included


def test_latam_eda_is_importable_read_only():
    from latam_eda import data, pipeline

    assert pipeline.SETTINGS["memory_limit"] == "4GB"
    assert callable(data.connect)
