# CLAUDE.md — Below Zero

Research project on the cost of grid constraints in Great Britain: what it costs to switch off
renewable generation the network can't carry, and what planned network investment could save.

**Output:** a 1,500–2,000 word public piece, three charts, and this public repo.
**Secondary purpose:** an application artefact for the Oxford MSc in Energy Systems — it needs to demonstrate that an economist can handle power system data. Readability and traceability matter as much as the result.

---

## The research question

> How much does Great Britain pay each month to switch off renewable generation its network can't
> carry, what does replacing that energy cost, and how much of it could planned transmission
> investment remove?

Every cost is **built bottom-up from half-hourly settlement data**, then reconciled against NESO's
published totals. The bottom-up build is the contribution; the published totals are the check.

## The three charts

Decide these before writing prose. If a chart doesn't make a reader pause, the paragraph attached to it won't either.

1. **Monthly cost of paid curtailment.** Sum, per month, of payments to renewable units (mainly
   wind) for accepted bids to reduce output, built from half-hourly BM unit data. Shows the trend
   and seasonality over three years.
2. **What network investment could remove — an upper bound.** Split curtailment by the transmission
   boundary it sits behind (mainly Scotland → England). For each half hour, ask how much curtailed
   volume would have fitted through the extra capacity planned for that boundary (e.g. Eastern
   Green Link 1 and 2). Labelled clearly as a **ceiling** on savings, not a forecast.
3. **Full cost of curtailment.** Payments to turn renewables down **plus** payments to turn
   replacement generation (mostly gas) up elsewhere, per month. This is what the switched-off
   energy actually cost, built entirely from BM data.

Charts must be readable in both light and dark, and legible when printed greyscale.

## Non-goals

- Descriptive "negative prices are rising" analysis.
- Battery/BESS arbitrage revenue modelling — commercially saturated, we would add nothing.
- A full network or market model: no re-dispatch simulation, no counterfactual wholesale prices
  (what prices *would* have been needs a supply-stack model — out of scope).
- A zonal pricing counterfactual.

---

## Data sources

**Elexon Insights API** — public, **no API key required**. Base: `https://data.elexon.co.uk/bmrs/api/v1`.

| Endpoint | Contents | Role | Status |
|---|---|---|---|
| `datasets/MID` | Market Index Data (exchange price, volume) | Wholesale price context | ✅ Verified (Stage 01) |
| `balancing/settlement/indicative/cashflows/all/{bid\|offer}/{date}/{period}` | Cashflow per BM unit per period | Charts 1 and 3 — primary cost source | ✅ Responds; sign convention **not yet verified** |
| `balancing/settlement/indicative/volumes/all/...` | Accepted volume per BM unit per period | Charts 1–3 — curtailed MWh | ⚠️ Not yet tested |
| `datasets/BOALF` | Bid-offer acceptances, with `soFlag` | Which actions were system (constraint) actions | ✅ Responds |
| `datasets/BOD` | Submitted bid/offer prices | Cross-check only | ✅ Responds — ~6,000 rows per period; **do not bulk-download** |
| `reference/bmunits/all` | BM unit reference (~3,100 units) | Unit → fuel type / location mapping | ✅ Responds |
| `datasets/FUELHH`, `INDO` | Generation by fuel, demand | Context (wind share at times of curtailment) | ⚠️ Not yet tested |

**NESO data portal** (CKAN API: `https://api.neso.energy/api/3/action/...`) — separate downloads.

| Dataset | Role |
|---|---|
| Constraint Breakdown Costs and Volume (`constraint-breakdown`) | Reconciliation of our bottom-up totals |
| Thermal Constraint Costs (`thermal-constraint-costs`) | Cost by boundary — chart 2 |
| 24 Months Ahead Constraint Limits | Future boundary capacity after reinforcement — chart 2 |
| Day Ahead Constraint Flows and Limits | Boundary flows vs limits — chart 2 (check how much history it holds) |

Note: NESO flagged column renames on several of these files from October 2026. Check headers when parsing.

**Study period:** three NESO financial years, April 2023 – March 2026, so totals line up with NESO's
yearly files. Indicative (not final settlement) values are used; see Known traps.

- Elexon developer portal: https://developer.data.elexon.co.uk/
- BMRS API docs: https://bmrs.elexon.co.uk/api-documentation
- NESO data portal: https://www.neso.energy/data-portal

---

## Stack — settled, do not revisit

- **Python.** Not R. The energy data community is Python and the repo is part of the deliverable.
- `requests` + `pandas` + **`plotnine`** (ggplot2 grammar — preferred over raw matplotlib for the three charts).
- **CSV cache on local disk.** No database, no parquet. Raw API responses are cached as received (JSON).
- No SQL. No Power BI.
- `venv` for the environment (Python 3.14). Public git repo from the first commit.

### Separation of concerns

- **Data pull = a plain `.py` script**, run from the terminal, writes to `data/raw/`. Never run from a notebook.
- **Analysis and charts = a notebook.** Reads only from the cache.

Notebooks lie about execution order; the multi-year pull must never live in a re-runnable cell.

---

## Conventions

1. **Write the raw API response to disk before parsing it.** Always. Parse from the cache, never from the live response.
2. **Never re-request a file already cached.** Check for the file first.
3. **Build the datetime index from `(settlementDate, settlementPeriod)` explicitly.** Settlement periods run 1–48 normally, but **46 and 50 on clock-change days**. Never assume 48, never infer the timestamp from row position.
4. **Every figure in the final piece must be traceable to a cached raw file.** If a number can't be regenerated from `data/raw/`, it doesn't go in.
5. **The BM unit → fuel type / location / boundary mapping lives in a committed CSV**, not in inline code. It is judgement-heavy and a reader needs to be able to audit it.
6. Commit as the work develops. A visible history is part of what this repo is demonstrating.

---

## Known traps

- **Paid curtailment is a lower bound on curtailment.** Accepted bids capture output turned down *with a balancing payment*. Some output is lost without one. The piece must say so.
- **Not every accepted wind bid is a constraint action.** Some are energy balancing. Use `soFlag` and NESO's own constraint categorisation; document the rule and how much it moves the total.
- **Not all constraint cost goes through the BM.** Trades, intertrip contracts (CMIS) and other constraint-management contracts sit outside it, so a BM-only total will sit below NESO's figure. Expected — quantify it, don't hide it.
- **Indicative ≠ final settlement.** The indicative cashflows are calculated shortly after the day; final settlement can differ. State which was used.
- **Cashflow sign conventions.** Verify on a hand-checked unit and period, using BOD prices × accepted volume, before trusting any total.
- **Replacement attribution is an estimate.** The data does not say which offer replaced which bid. Chart 3's method must be stated plainly and kept simple.
- **Chart 2 is a ceiling.** Extra boundary capacity doesn't remove every constraint (local constraints, outages, other boundaries). Never present it as a forecast saving.
- **`MID` zero rows mean "no index".** When traded volume misses Elexon's liquidity threshold, price and volume both default to zero. Treat zero-volume rows as missing, not as £0. `N2EXMIDP` is all zeros; use `APXMIDP`.
- **BM unit mapping is where most of the hours will go.** Budget for it.
- **Reconciliation may fail.** If our total diverges from NESO's, that investigation *is* the interesting result. Do not fudge toward agreement.

---

## Stages

Each stage produces something publishable on its own, so the project survives being abandoned halfway.

- **01 — One day of prices, end to end.** ✅ Done. `MID` for 7 April 2024: fetch, cache, parse, plot.
- **02 — One day of balancing cost, end to end.** Same day. Pull indicative bid/offer cashflows and volumes plus `BOALF`; verify the sign convention by hand on one unit; total what was paid to wind to turn down. No loops.
- **03 — BM unit mapping.** Build `data/bmunit_map.csv`: fuel type, Scotland vs England & Wales, boundary. Document every judgement call.
- **04 — Three years, cached; charts 1 and 3.** Loop over the study period, cache everything, parse from disk. Monthly curtailment cost and full replacement cost. Reconcile against NESO constraint breakdown.
- **05 — Boundaries; chart 2.** NESO boundary costs, limits and planned capacity. Compute the upper bound on what reinforcement could remove.

---

## Suggested layout

```
below-zero/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .gitignore          # excludes data/raw/
├── src/
│   ├── fetch.py        # the pull — run from the terminal
│   ├── parse.py        # cache → tidy frames
│   └── mapping.py      # BM unit → fuel/location/boundary
├── data/
│   ├── raw/            # cached API responses, gitignored
│   ├── samples/        # small readable copies of raw responses, committed
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
