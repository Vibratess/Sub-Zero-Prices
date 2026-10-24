# CLAUDE.md — Below Zero

Research project on negative electricity prices in Great Britain.

**Output:** a 1,500–2,000 word public piece, three charts, and this public repo.
**Secondary purpose:** an application artefact for the Oxford MSc in Energy Systems — it needs to demonstrate that an economist can handle power system data. Readability and traceability matter as much as the result.

---

## The research question

Do not drift from this. The project is **not** "negative prices are increasing" — that is descriptive, already covered commercially (Modo Energy publish monthly), and adds nothing.

The thesis is:

> "Negative prices" in Great Britain refers to at least three distinct phenomena that occur at different times, for different reasons, with different policy implications — and commentary routinely conflates them.

The three:

| # | Phenomenon | What it means | Dataset |
|---|---|---|---|
| 1 | Wholesale / day-ahead price below zero | Genuine expected oversupply, priced a day ahead | `MID` |
| 2 | Imbalance / system price below zero | System was long in real time — a forecast-error story, not an oversupply story | system prices |
| 3 | Negative **accepted bids** in the Balancing Mechanism | A generator paying to be switched off — this is paid curtailment | `BOD` + `BOAL` |

The deliverable is: separate them, measure the incidence of each, and test whether they coincide. If they don't move together, the thesis is proven.

## Non-goals

- Descriptive "negative prices are rising" analysis.
- Battery/BESS arbitrage revenue modelling — commercially saturated, we would add nothing.
- A zonal pricing counterfactual — needs a proper market model, out of scope.

---

## Data sources

**Elexon Insights API** — public, **no API key required** (stated on their developer portal).

> ⚠️ The base path and query parameter names are **UNVERIFIED**. The dataset codes below come from Elexon's developer portal listing, but no request has been executed against the live API. Confirm the exact request syntax against the live documentation before building anything on top of it. Treat Stage 01 as that test.

| Code | Contents | Role |
|---|---|---|
| `MID` | Market Index Data (exchange-derived) | Primary wholesale price series — phenomenon 1 |
| `BOD` | Bid Offer Data (prices submitted) | Phenomenon 3 |
| `BOAL` | Bid Offer Acceptance Level (what was accepted) | Phenomenon 3 |
| `FUELHH` | Half-hourly generation outturn by fuel | Wind output |
| `FUELINST` | Instantaneous generation by fuel | Fallback / cross-check |
| `INDO` | Initial Demand Outturn | Residual demand |
| `ITSDO` | Initial Transmission System Demand Outturn | Residual demand |
| `WINDFOR` | Wind generation forecast | Forecast-error test (Stage 04) |
| `reference/bmunits/all` | BM unit reference | Unit → fuel type / location mapping |

**NESO data portal** — "Constraint Breakdown Costs and Volume". Used in Stage 05 to validate the Stage 05 figure against published constraint costs. Not Elexon; separate download.

- Elexon developer portal: https://developer.data.elexon.co.uk/
- BMRS API docs: https://bmrs.elexon.co.uk/api-documentation
- NESO constraint breakdown: https://www.neso.energy/data-portal/constraint-breakdown

---

## Stack — settled, do not revisit

- **Python.** Not R. The energy data community is Python and the repo is part of the deliverable.
- `requests` + `pandas` + **`plotnine`** (ggplot2 grammar — preferred over raw matplotlib for the three charts).
- **CSV cache on local disk.** No database, no parquet. Three years of half-hourly data is ~52,000 rows per series; anything heavier is over-engineering.
- No SQL. No Power BI.
- `venv` for the environment. Public git repo from the first commit.

### Separation of concerns

- **Data pull = a plain `.py` script**, run once, writes to `data/raw/`. Never run from a notebook.
- **Analysis and charts = a notebook.** Reads only from the cache.

Notebooks lie about execution order; the three-year pull must never live in a re-runnable cell.

---

## Conventions

1. **Write the raw API response to disk before parsing it.** Always. Parse from the cache, never from the live response.
2. **Never re-request a date already cached.** Check for the file first.
3. **Build the datetime index from `(settlementDate, settlementPeriod)` explicitly.** Settlement periods run 1–48 normally, but **46 and 50 on clock-change days**. Never assume 48, never infer the timestamp from row position. This will silently corrupt an annual series otherwise.
4. **Every figure in the final piece must be traceable to a cached raw file.** If a number can't be regenerated from `data/raw/`, it doesn't go in.
5. **The BM unit → fuel type / location mapping lives in a committed CSV**, not in inline code. It is judgement-heavy and a reader needs to be able to audit it.
6. Commit as the work develops. A visible history is part of what this repo is demonstrating.

---

## Known traps

- **Paid curtailment is a lower bound on curtailment.** Negative accepted bids capture output turned down *with a balancing payment*. Some output is lost without one. The final piece must state this explicitly — it protects the whole argument.
- **`MID` may carry one row per exchange rather than one per settlement period.** Check. If so, decide between a volume-weighted average and a single venue, and document which and why.
- **BM unit mapping is where most of the hours will go.** Budget for it. Don't start Stage 05 expecting it to be quick.
- **Reconciliation may fail in Stage 05.** If the computed total diverges from NESO's published constraint costs, that investigation *is* the interesting result. "Here is why the obvious calculation doesn't reconcile with the published figure" is a better paper than a number that happens to match. Do not fudge toward agreement.

---

## Stages

Each stage produces something publishable on its own, so the project survives being abandoned halfway.

- **01 — One day, end to end.** Pull a single settlement day of `MID`, parse, index by settlement period, plot. No loops. The goal is learning the response shape, the datetime conventions, and confirming the endpoint syntax.
- **02 — Three years of prices, cached.** Loop over dates, cache every raw response, parse from disk.
- **03 — Join wind and demand.** Add `FUELHH` and `INDO`; construct residual demand (demand − wind − solar). Produce the price vs residual demand scatter.
- **04 — Add the imbalance price; test the forecast-error story.** Conditional on the day-ahead price being positive, how often is the imbalance price negative, and does that track wind forecast error? This is the empirical core of the 1-vs-2 distinction.
- **05 — Negative bids.** `BOD` + `BOAL`, map units to fuel via the reference endpoint, filter to wind, find accepted negative-priced bids, total what was paid. Reconcile against NESO constraint costs.

---

## The three charts

Decide these before writing prose. If a chart doesn't make a reader pause, the paragraph attached to it won't either.

1. **Incidence by phenomenon over time** — share of settlement periods per month where each of the three prices was negative. Three series, monthly, three years. The headline is whether they move together.
2. **Price against residual demand** — every settlement period as a point, zero line marked, negative observations coloured. Shows the left tail of the supply curve and where it crosses zero. Handle overplotting (alpha or hexbin).
3. **When it happens** — hour of day × month heatmap, shaded by frequency of negative prices. 24 × 36. Cheap and immediately legible.

Charts must be readable in both light and dark, and legible when printed greyscale.

---

## Suggested layout

```
below-zero/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .gitignore          # excludes data/raw/
├── src/
│   ├── fetch.py        # the pull — run once per dataset
│   ├── parse.py        # cache → tidy frames
│   └── mapping.py      # BM unit → fuel/location
├── data/
│   ├── raw/            # cached API responses, gitignored
│   ├── bmunit_map.csv  # committed, auditable
│   └── tidy/           # parsed outputs
├── notebooks/
│   └── analysis.ipynb
└── figures/
```

---

## House style for the written piece

- Plain prose. No throat-clearing, no "in this paper I will".
- State the finding, then the method, then the caveats. Caveats are short and specific, not hedging.
- Every number in the text appears in a chart or a table.
- A short method note at the end, and a link to this repo.
- Target: 1,500–2,000 words. Resist growth.
