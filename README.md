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

python src/fetch.py 2024-04-07 --period 23   # one settlement day into data/raw/ (skips what's cached)
```

Then open `notebooks/analysis.ipynb`. The notebook reads only from `data/raw/` and never calls
the API.

## Data

Elexon Insights API (`https://data.elexon.co.uk/bmrs/api/v1`), public, no key required.

| Dataset | Used for | Notes |
|---|---|---|
| `MID` (Market Index Data) | Wholesale price context | Volume-weighted average price of exchange trades for delivery in each half hour. When volume misses Elexon's liquidity threshold, price and volume default to zero, so zero-volume rows are treated as missing. `N2EXMIDP` is all zeros, so only `APXMIDP` is used. |

| `EBOCF` (indicative cashflows) | Cash paid to or by each BM unit, per half hour | Positive = paid to the unit. Checked by hand: settled volume × accepted price reproduces it exactly. |
| `BOAV` (acceptance volumes) | Settled MWh of each accepted action | Used rather than `DISPTAV`, whose volume versions are built for imbalance pricing and don't match the cash. |
| `BOALF` (acceptances) | Whether each action was flagged as a system action (`soFlag`) | Joined to `BOAV` on acceptance number. |
| BM unit register | Fuel type per unit | Provisional until the committed mapping (`data/bmunit_map.csv`) is built. |

## Conventions

- Raw API responses are saved to disk unchanged before anything is parsed.
- Timestamps are built from `(settlementDate, settlementPeriod)`: a settlement day starts at
  midnight London time, and each period is 30 minutes of elapsed time. Clock-change days have
  46 (March) or 50 (October) periods. The parser checks its timestamps against the API's own
  `startTime`.
