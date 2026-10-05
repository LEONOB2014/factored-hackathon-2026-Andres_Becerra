# LATAM Bank Grain Atlas

The exploratory phase read at four grains: **event** (the source as delivered), **country** (the platform rebuilt
per market, and with the backup as the source), **daily** (day, month and campaign cell) and **hourly** (each
process on its own delivery clock). Each grain has the same six groups of views (Overview, Data, Findings, Pipeline,
Walkthrough, Decide): 75 views, plus Mission control, a shared decision board, a notebook index and a glossary.

It is published as a private claude.ai artifact; `grain_atlas.html` here is the exact page.

## Files

| file | what it is |
|---|---|
| `grain_atlas.html` | the built page (one self-contained file) |
| `data_atlas.html` | the earlier LATAM Bank Data Atlas; its modules, charts and data are reused |
| `aggregates.json` | counts by hour, weekday, day and bucket from the dataset: no identifiers |
| `extract.py` | splits `data_atlas.html` into modules and its JS |
| `build.py` | assembles the page from the modules, `../../tables/*.csv`, `aggregates.json` and `src/` |
| `live_aggs.py` | recomputes `aggregates.json` from the parquet dataset |
| `src/` | page shell, styles, view catalogue (`views.js`), layout engine (`core.js`), charts (`renderers.js`), decision board (`decisions.js`) |

## Rebuild

From `eda/`:

```bash
uv run python reports/dashboards/grain_atlas/build.py
```

`aggregates.json` needs the git-ignored dataset in `data/parquet`; regenerate it only when the dataset changes:

```bash
uv run python reports/dashboards/grain_atlas/live_aggs.py ../data/parquet \
    reports/dashboards/grain_atlas/aggregates.json
```

Every process is placed on its delivery-day clock (ADR-014): −6 h for transactions, digital events and sends,
−8 h for contacts and complaints.

## Editing

- A view is one `VW(grain, group, id, title, options)` call in `src/views.js`. A view either reuses a Data Atlas
  module (`mod`, `subs`) or composes blocks (`S(title, lede, body)`, `FIG`, `TBL`, `P` for notes).
- `core.js` lays each view out as a dashboard: `.kpis` go to the top strip, each `h3` starts a card, every
  `details.panel` moves to the notes column, and a calculator gets its own card.
- The decision board stores choices in the artifact's shared database (collection `decisions`); without it, the
  page falls back to the browser's local storage.
