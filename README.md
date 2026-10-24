# Below Zero

How much does Great Britain pay each month to switch off renewable generation its network can't
carry, what does replacing that energy cost, and how much of it could planned transmission
investment remove? Every cost is built bottom-up from half-hourly Elexon settlement data, then
reconciled against NESO's published constraint costs.

Work in progress. See `CLAUDE.md` for the research question and plan.

## Running it

```
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python src/fetch.py 2024-04-07      # download one settlement day into data/raw/ (skips if cached)
```

Then open `notebooks/analysis.ipynb`. The notebook reads only from `data/raw/` and never calls
the API.

## Data

Elexon Insights API (`https://data.elexon.co.uk/bmrs/api/v1`), public, no key required.

| Dataset | Used for | Notes |
|---|---|---|
| `MID` (Market Index Data) | Wholesale price context | Volume-weighted average price of exchange trades for delivery in each half hour. When volume misses Elexon's liquidity threshold, price and volume default to zero, so zero-volume rows are treated as missing. `N2EXMIDP` is all zeros, so only `APXMIDP` is used. |

## Conventions

- Raw API responses are saved to disk unchanged before anything is parsed.
- Timestamps are built from `(settlementDate, settlementPeriod)`: a settlement day starts at
  midnight London time, and each period is 30 minutes of elapsed time. Clock-change days have
  46 (March) or 50 (October) periods. The parser checks its timestamps against the API's own
  `startTime`.
