"""Turn cached raw API responses from data/raw/ into tidy pandas DataFrames.

Nothing here touches the network: every function reads from a file on disk.
"""

import gzip
import json
from pathlib import Path

import pandas as pd

LONDON = "Europe/London"
HALF_HOUR = pd.Timedelta(minutes=30)

# MID is published by two providers. N2EXMIDP almost always shows price 0 at volume 0,
# i.e. no index (see below): over April 2023 - March 2026 it carried 0.01% of traded
# volume, on 49 days. So we use APX only. parse_mid() warns on days N2EX has volume.
MID_PROVIDER = "APXMIDP"


# --- Shared helpers ----------------------------------------------------------------------

def load_raw(path: Path) -> dict | list:
    """Read a cached response (gzip-compressed JSON) exactly as the API sent it."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load_records(path: Path) -> pd.DataFrame:
    """Read a cached response as a table. Most endpoints wrap their records in a "data" key."""
    raw = load_raw(path)
    return pd.DataFrame(raw["data"] if isinstance(raw, dict) else raw)


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


def checked_start_utc(df: pd.DataFrame, path: Path) -> pd.Series:
    """Build start times from (settlementDate, settlementPeriod) and confirm they match
    the startTime the API reports, so a timestamp error can never pass silently."""
    start_utc = settlement_period_start(df["settlementDate"], df["settlementPeriod"])
    api_start = pd.to_datetime(df["startTime"], utc=True)
    if not (api_start == start_utc).all():
        raise ValueError(f"{path.name}: computed start times disagree with the API's startTime")
    return start_utc


# --- Market Index Data: wholesale price -------------------------------------------------

def parse_mid(path: Path) -> pd.DataFrame:
    """Read one cached MID file and return one row per settlement period (APX only)."""
    df = load_records(path)

    # Check the single-provider decision still holds for this file.
    other = df[(df["dataProvider"] != MID_PROVIDER) & (df["volume"] > 0)]
    if not other.empty:
        print(f"WARNING {path.name}: {len(other)} non-APX rows have positive volume")
    df = df[df["dataProvider"] == MID_PROVIDER].copy()
    df["start_utc"] = checked_start_utc(df, path)

    # At most one row per period, all within 1..N (N depends on clock changes). A period
    # Elexon did not publish (6 in three years) is added back with a missing price, so
    # every day has its full set of rows; a duplicate or impossible period is an error.
    date = df["settlementDate"].iloc[0]
    n_periods = periods_in_day(date)
    if df["settlementPeriod"].duplicated().any() or not df["settlementPeriod"].between(1, n_periods).all():
        raise ValueError(f"{path.name}: duplicate or out-of-range settlement periods")
    full = pd.DataFrame({"settlementDate": date, "settlementPeriod": range(1, n_periods + 1)})
    full["start_utc"] = settlement_period_start(full["settlementDate"], full["settlementPeriod"])
    df = full.merge(df, on=["settlementDate", "settlementPeriod", "start_utc"], how="left")
    if df["price"].isna().any():
        print(f"{path.name}: {df['price'].isna().sum()} periods not published, price set to missing")

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


# --- Balancing Mechanism -----------------------------------------------------------------

def parse_cashflows(path: Path) -> pd.DataFrame:
    """One row per BM unit per period: the indicative cashflow (EBOCF), in £.

    Sign convention, verified by hand in the notebook: positive = paid TO the unit.
    A wind farm turned down (negative volume) at a negative bid price is paid.
    """
    df = load_records(path)

    # The API should return only the latest calculation run, but on one day in three
    # years (16 Oct 2023, periods 37-39) it returned two. Keep the latest run.
    df = df.sort_values("createdDateTime")
    repeats = df.duplicated(["bmUnit", "settlementPeriod"], keep="last")
    if repeats.any():
        print(f"{path.name}: {repeats.sum()} rows from an earlier calculation run dropped")
        df = df[~repeats]

    return pd.DataFrame({
        "settlement_date": df["settlementDate"],
        "settlement_period": df["settlementPeriod"],
        "start_utc": checked_start_utc(df, path),
        "bm_unit": df["bmUnit"],
        "cashflow_gbp": df["totalCashflow"],
    })


def parse_boav(path: Path) -> pd.DataFrame:
    """One row per acceptance per unit per period: the settled volume (BOAV), in MWh.

    Negative = output reduced (bids), positive = output increased (offers).
    """
    df = load_records(path)
    return pd.DataFrame({
        "settlement_date": df["settlementDate"],
        "settlement_period": df["settlementPeriod"],
        "start_utc": checked_start_utc(df, path),
        "bm_unit": df["bmUnit"],
        "acceptance_number": df["acceptanceId"],
        "volume_mwh": df["totalVolumeAccepted"],
    })


def parse_boalf(paths: Path | list[Path]) -> pd.DataFrame:
    """One row per acceptance, with its system-action flag (soFlag).

    Takes one file, or a list (the autumn clock-change day is cached in two parts).
    A raw acceptance has several rows (points on its output profile), and can appear in
    both parts; the flag must be the same on all of them, which is checked here.
    """
    paths = [paths] if isinstance(paths, Path) else paths
    df = pd.concat([load_records(p) for p in paths], ignore_index=True)
    flags = df.groupby(["bmUnit", "acceptanceNumber"])["soFlag"].agg(["first", "nunique"])
    if (flags["nunique"] > 1).any():
        raise ValueError(f"{paths[0].name}: an acceptance has conflicting soFlag values")
    return pd.DataFrame({
        "bm_unit": flags.index.get_level_values("bmUnit"),
        "acceptance_number": flags.index.get_level_values("acceptanceNumber"),
        "so_flag": flags["first"].to_numpy(),
    })


def parse_bmunits(path: Path) -> pd.DataFrame:
    """The BM unit register, keeping the columns the mapping needs."""
    df = load_records(path)
    df = df[df["elexonBmUnit"].notna()]
    tidy = pd.DataFrame({
        "bm_unit": df["elexonBmUnit"],
        "ng_bm_unit": df["nationalGridBmUnit"],
        "name": df["bmUnitName"],
        "fuel_type": df["fuelType"],
        "gsp_group": df["gspGroupName"],
        "lead_party": df["leadPartyName"],
        "generation_capacity_mw": pd.to_numeric(df["generationCapacity"], errors="coerce"),
    })
    # The register lists at least one unit twice (T_WLNYO-4). Drop exact copies, and
    # fail if a unit appears twice with different details, since joins would double-count.
    tidy = tidy.drop_duplicates()
    if tidy["bm_unit"].duplicated().any():
        raise ValueError(f"{path.name}: a BM unit appears twice with different details")
    return tidy.reset_index(drop=True)
