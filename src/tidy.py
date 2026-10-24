"""Build the tidy tables the analysis reads, from the raw cache only (no network).

Run from the project root, after src/fetch.py and src/mapping.py:
    python src/tidy.py 2023-04-01 2026-03-31

Writes to data/tidy/:
  halfhourly.csv      one row per settlement period: wholesale price, paid curtailment of
                      wind (by side of the grid and soFlag), and system-flagged offers from
                      other units (the replacement generation)
  daily_by_fuel.csv   one row per day x side x fuel x flag: cash and volume for every unit,
                      to check how much cash the wind mapping covers
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from fetch import boalf_cache_paths, boav_cache_path, bmunits_cache_path, cashflow_cache_path, mid_cache_path
from parse import parse_bmunits, parse_boalf, parse_boav, parse_cashflows, parse_mid

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TIDY_DIR = DATA_DIR / "tidy"
UNIT_PERIOD = ["bm_unit", "settlement_period"]


def acceptance_cash(settlement_date: str, side: str, flags: pd.DataFrame) -> pd.DataFrame:
    """Every non-zero accepted volume for one day and side, with its soFlag and cash.

    Cash is published per unit per period, not per acceptance, so it is shared across a
    unit's acceptances in that period in proportion to volume. That is exact whenever they
    share a flag; `mixed_flags` marks the rows where it is a genuine split.
    """
    volumes = parse_boav(boav_cache_path(settlement_date, side))
    volumes = volumes[volumes["volume_mwh"] != 0]
    cash = parse_cashflows(cashflow_cache_path(settlement_date, side))

    df = volumes.merge(flags, on=["bm_unit", "acceptance_number"], how="left")
    df["action"] = df["so_flag"].map({True: "system", False: "energy"}).fillna("unknown")
    df["share"] = df["volume_mwh"] / df.groupby(UNIT_PERIOD)["volume_mwh"].transform("sum")
    df = df.merge(cash[UNIT_PERIOD + ["cashflow_gbp"]], on=UNIT_PERIOD, how="left")
    df["cash_gbp"] = df["share"] * df["cashflow_gbp"].fillna(0)
    df["mixed_flags"] = df.groupby(UNIT_PERIOD)["action"].transform("nunique") > 1
    df["side"] = side
    return df


def build_day(settlement_date: str, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Half-hourly and by-fuel tables for one settlement day."""
    flags = parse_boalf(boalf_cache_paths(settlement_date))
    acc = pd.concat([acceptance_cash(settlement_date, side, flags) for side in ["bid", "offer"]])
    acc = acc.merge(units, on="bm_unit", how="left")
    acc["fuel_type"] = acc["fuel_type"].fillna("not set in register")
    acc["is_wind"] = acc["region"].notna()

    # By fuel: everything, for the coverage check
    by_fuel = (acc.groupby(["settlement_date", "side", "fuel_type", "action"], as_index=False)
                  [["cash_gbp", "volume_mwh"]].sum())

    # Paid curtailment: accepted wind bids, wide by side of the grid and flag
    wind_bids = acc[acc["is_wind"] & (acc["side"] == "bid")]
    curtail = wind_bids.pivot_table(index="settlement_period", columns=["host_to", "action"],
                                    values=["cash_gbp", "volume_mwh"], aggfunc="sum", fill_value=0)
    curtail.columns = [f"wind_bid_{measure}_{host}_{action}" for measure, host, action in curtail.columns]

    # Replacement: system-flagged offers from every unit that is not wind
    repl = acc[~acc["is_wind"] & (acc["side"] == "offer") & (acc["action"] == "system")]
    repl = repl.groupby("settlement_period")[["cash_gbp", "volume_mwh"]].sum().add_prefix("system_offer_")

    mid = parse_mid(mid_cache_path(settlement_date)).set_index("settlement_period")
    half = (mid[["settlement_date", "start_utc", "price_gbp_mwh"]].rename(columns={"price_gbp_mwh": "mid_price_gbp_mwh"})
            .join(curtail).join(repl))
    half["wind_bid_cash_mixed_flags_gbp"] = wind_bids[wind_bids["mixed_flags"]].groupby("settlement_period")["cash_gbp"].sum()
    return half.reset_index(), by_fuel


def wind_units() -> pd.DataFrame:
    """Register fuel type for every unit, plus region / host TO for mapped wind units."""
    units = parse_bmunits(bmunits_cache_path())[["bm_unit", "fuel_type"]]
    wind_map = pd.read_csv(DATA_DIR / "bmunit_map.csv")[["bm_unit", "region", "host_to"]]
    return units.merge(wind_map, on="bm_unit", how="left")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build tidy tables from the raw cache.")
    parser.add_argument("start")
    parser.add_argument("end")
    args = parser.parse_args()

    units = wind_units()
    halves, fuels, missing = [], [], []
    for d in pd.date_range(args.start, args.end).strftime("%Y-%m-%d"):
        try:
            half, by_fuel = build_day(d, units)
        except FileNotFoundError as error:
            missing.append(d)
            print(f"{d}: not fully cached ({Path(error.filename).name}), skipped")
            continue
        halves.append(half)
        fuels.append(by_fuel)

    TIDY_DIR.mkdir(parents=True, exist_ok=True)
    halfhourly = pd.concat(halves, ignore_index=True)
    # Columns only appear on days where that combination occurs; elsewhere it was zero
    value_cols = [c for c in halfhourly.columns if c.startswith(("wind_bid_", "system_offer_"))]
    halfhourly[value_cols] = halfhourly[value_cols].fillna(0)
    halfhourly.to_csv(TIDY_DIR / "halfhourly.csv", index=False)
    pd.concat(fuels, ignore_index=True).to_csv(TIDY_DIR / "daily_by_fuel.csv", index=False)
    print(f"Wrote {len(halfhourly):,} half-hours from {len(halves)} days; {len(missing)} days skipped: {missing}")
