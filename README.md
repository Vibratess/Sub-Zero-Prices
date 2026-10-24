# Below Zero

Negative electricity prices in Great Britain are at least three different things: a negative
wholesale price, a negative imbalance price, and negative accepted bids in the Balancing
Mechanism (paid curtailment). This project separates them, measures how often each happens,
and tests whether they move together.

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
| `MID` (Market Index Data) | Wholesale price | Two providers are published. `N2EXMIDP` shows price 0 at volume 0 in every period checked, so only `APXMIDP` is used. The parser warns if N2EX ever carries volume. |

## Conventions

- Raw API responses are saved to disk unchanged before anything is parsed.
- Timestamps are built from `(settlementDate, settlementPeriod)`: a settlement day starts at
  midnight London time, and each period is 30 minutes of elapsed time. Clock-change days have
  46 (March) or 50 (October) periods. The parser checks its timestamps against the API's own
  `startTime`.
