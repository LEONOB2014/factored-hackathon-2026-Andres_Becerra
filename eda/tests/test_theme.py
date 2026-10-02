"""latam_eda.theme: the chart palette and plotly template every notebook registers."""

import re

import plotly.io as pio

from latam_eda import theme

HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_palettes_are_valid_hex_colours():
    for colour in [
        *theme.CATEGORICAL,
        *theme.SEQ_BLUE,
        *theme.DIV,
        *theme.STATUS.values(),
        theme.SURFACE,
        theme.INK,
        theme.INK2,
        theme.GRID,
    ]:
        assert HEX.match(colour), colour


def test_categorical_slots_are_distinct_and_fixed():
    assert len(theme.CATEGORICAL) == len(set(theme.CATEGORICAL)) == 8
    assert theme.CATEGORICAL[0] == theme.BLUE


def test_main_and_backup_keep_different_colours():
    assert theme.MAIN_C != theme.BACKUP_C
    assert {theme.MAIN_C, theme.BACKUP_C} <= set(theme.CATEGORICAL)


def test_diverging_palette_has_a_neutral_midpoint():
    assert len(theme.DIV) % 2 == 1


def test_register_sets_the_default_template():
    previous = pio.templates.default
    try:
        theme.register()
        assert pio.templates.default == "latam"
        layout = pio.templates["latam"].layout
        assert list(layout.colorway) == theme.CATEGORICAL
        assert layout.paper_bgcolor == theme.SURFACE
    finally:
        pio.templates.default = previous
