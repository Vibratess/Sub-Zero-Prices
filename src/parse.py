"""Turn cached raw API responses from data/raw/ into tidy pandas DataFrames.

Nothing here touches the network: every function reads from a file on disk.
"""

import json
from pathlib import Path

import pandas as pd

LONDON = "Europe/London"
HALF_HOUR = pd.Timedelta(minutes=30)

# MID is published by two providers. In every period checked so far N2EXMIDP shows
# price 0 at volume 0, i.e. no index (see below), so we use APX only. parse_mid() re-checks this
# on every file and warns if N2EX ever carries real volume.
MID_PROVIDER = "APXMIDP"


def settlement_period_start(settlement_date: pd.Series, settlement_period: pd.Series) -> pd.Series:
    """UTC start time of each settlement period.

    A settlement day starts at midnight London time, and period n starts (n - 1) x 30
    minutes of real elapsed time later. Doing the addition in UTC handles clock-change
    days correctly: the March day has 46 periods and the October day has 50.
    """
    local_midnight = pd.to_datetime(settlement_date).dt.tz_localize(LONDON)
    return local_midnight.dt.tz_convert("UTC") + (settlement_period - 1) * HALF_HOUR


def periods_in_day(settlement_date: str) -> int:
    """Number of settlement periods in a day: 48, or 46 / 50 on clock-change days."""
    day = pd.Timestamp(settlement_date)
    start = day.tz_localize(LONDON)
    end = (day + pd.Timedelta(days=1)).tz_localize(LONDON)
    return int((end - start) / HALF_HOUR)


def parse_mid(path: Path) -> pd.DataFrame:
    """Read one cached MID file and return one row per settlement period (APX only)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    df = pd.DataFrame(raw["data"])

    # Check the single-provider decision still holds for this file.
    other = df[(df["dataProvider"] != MID_PROVIDER) & (df["volume"] > 0)]
    if not other.empty:
        print(f"WARNING {path.name}: {len(other)} non-APX rows have positive volume")
    df = df[df["dataProvider"] == MID_PROVIDER].copy()

    # Build the timestamp from (settlementDate, settlementPeriod) ourselves, then
    # confirm it agrees with the startTime the API reports.
    df["start_utc"] = settlement_period_start(df["settlementDate"], df["settlementPeriod"])
    api_start = pd.to_datetime(df["startTime"], utc=True)
    if not (api_start == df["start_utc"]).all():
        raise ValueError(f"{path.name}: computed start times disagree with the API's startTime")

    # Exactly one row for each period 1..N, where N depends on clock changes.
    for date, group in df.groupby("settlementDate"):
        expected = list(range(1, periods_in_day(date) + 1))
        if sorted(group["settlementPeriod"]) != expected:
            raise ValueError(f"{path.name}: {date} does not have exactly periods 1..{expected[-1]}")

    # Below Elexon's liquidity threshold, price and volume both default to zero.
    # That means "no index", not "the price was £0", so record it as missing.
    no_index = df["volume"] == 0
    if no_index.any():
        print(f"{path.name}: {no_index.sum()} periods below liquidity threshold, price set to missing")
    df["price"] = df["price"].mask(no_index)

    tidy = pd.DataFrame({
        "settlement_date": df["settlementDate"],
        "settlement_period": df["settlementPeriod"],
        "start_utc": df["start_utc"],
        "start_local": df["start_utc"].dt.tz_convert(LONDON),
        "price_gbp_mwh": df["price"],
        "volume_mwh": df["volume"],
    })
    return tidy.sort_values("start_utc").reset_index(drop=True)
