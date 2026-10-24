"""Download raw data from the Elexon Insights API and cache it, unchanged, in data/raw/.

Run from the project root:
    python src/fetch.py 2024-04-07                    # every daily dataset for one date
    python src/fetch.py 2023-04-01 2026-03-31         # every date in a range (inclusive)
    python src/fetch.py 2024-04-07 --period 23        # also the acceptance detail for period 23

No API key is needed. Files already in the cache are never re-requested, so an interrupted
range run picks up where it stopped when re-run with the same dates.
"""

import argparse
import ctypes
import gzip
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from parse import periods_in_day

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
NESO_URL = "https://api.neso.energy"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

PAUSE_SECONDS = 0.5                # after every real download, to stay well inside API quotas
RETRY_WAITS = [5, 30, 120, 300]    # seconds to wait before each retry of a failed request


def download_to_cache(endpoint: str, params: dict, path: Path, base: str = BASE_URL) -> Path:
    """GET one endpoint and save the response bytes to `path`, unless already cached.

    Rate limiting (429), server errors (5xx) and dropped connections are retried after
    increasing waits; anything else (e.g. 400 Bad Request) fails immediately.
    """
    if path.exists():
        return path

    for attempt, wait in enumerate([0] + RETRY_WAITS):
        time.sleep(wait)
        try:
            response = requests.get(f"{base}/{endpoint}", params=params, timeout=120)
        # ChunkedEncodingError = the connection dropped partway through the response
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as error:
            print(f"  connection error on {path.name} (attempt {attempt + 1}): {error.__class__.__name__}")
            continue
        if response.status_code == 429 or response.status_code >= 500:
            print(f"  HTTP {response.status_code} on {path.name} (attempt {attempt + 1})")
            continue
        response.raise_for_status()
        break
    else:
        raise RuntimeError(f"gave up on {path.name} after {len(RETRY_WAITS) + 1} attempts")

    # Save the bytes exactly as received, gzip-compressed (JSON shrinks ~25x, and
    # decompressing gives back the identical bytes). All parsing happens later, from this file.
    # Write under a temporary name, then rename: if the run is stopped mid-write, no
    # half-written file is left behind looking like a complete cache entry.
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(gzip.compress(response.content))
    partial.replace(path)
    time.sleep(PAUSE_SECONDS)
    return path


# --- Market Index Data: wholesale price -------------------------------------------------

def mid_cache_path(settlement_date: str) -> Path:
    """Where the raw Market Index Data response for one settlement date is stored."""
    return RAW_DIR / "MID" / f"MID_{settlement_date}.json.gz"


def fetch_mid_day(settlement_date: str) -> Path:
    """One settlement day of Market Index Data (MID)."""
    # When settlementPeriodFrom/To are given, the API reads from/to as settlement
    # dates rather than timestamps. Period 50 covers the long autumn clock-change day.
    params = {
        "from": settlement_date,
        "to": settlement_date,
        "settlementPeriodFrom": 1,
        "settlementPeriodTo": 50,
        "format": "json",
    }
    return download_to_cache("datasets/MID", params, mid_cache_path(settlement_date))


# --- Balancing Mechanism: what was paid, and for how much energy -------------------------

def cashflow_cache_path(settlement_date: str, bid_offer: str) -> Path:
    return RAW_DIR / "EBOCF" / f"EBOCF_{bid_offer}_{settlement_date}.json.gz"


def fetch_cashflows_day(settlement_date: str, bid_offer: str) -> Path:
    """Indicative cashflow per BM unit per period (EBOCF), for bids or offers."""
    endpoint = f"balancing/settlement/indicative/cashflows/all/{bid_offer}/{settlement_date}"
    return download_to_cache(endpoint, {"format": "json"}, cashflow_cache_path(settlement_date, bid_offer))


def boav_cache_path(settlement_date: str, bid_offer: str) -> Path:
    return RAW_DIR / "BOAV" / f"BOAV_{bid_offer}_{settlement_date}.json.gz"


def fetch_boav_day(settlement_date: str, bid_offer: str) -> Path:
    """Settled volume per acceptance (BOAV), for bids or offers. Quota-limited endpoint.

    Used instead of the indicative volumes (DISPTAV): BOAV x price reproduces every
    EBOCF cashflow checked, while DISPTAV's versions are built for imbalance pricing.
    """
    endpoint = f"balancing/settlement/acceptance/volumes/all/{bid_offer}/{settlement_date}"
    return download_to_cache(endpoint, {"format": "json"}, boav_cache_path(settlement_date, bid_offer))


def boalf_cache_path(settlement_date: str) -> Path:
    return RAW_DIR / "BOALF" / f"BOALF_{settlement_date}.json.gz"


def boalf_late_cache_path(settlement_date: str) -> Path:
    """Periods 49-50 of the autumn clock-change day, cached separately (see below)."""
    return RAW_DIR / "BOALF" / f"BOALF_{settlement_date}_SP49-50.json.gz"


def boalf_cache_paths(settlement_date: str) -> list[Path]:
    """All BOALF files for one date: one normally, two on the 50-period autumn day."""
    late = boalf_late_cache_path(settlement_date)
    return [boalf_cache_path(settlement_date)] + ([late] if late.exists() else [])


def fetch_boalf_day(settlement_date: str) -> Path:
    """Every bid-offer acceptance for one settlement day, with its system (soFlag) flag.

    BOALF rejects requests longer than one day, and counts the 25-hour autumn clock-change
    day as too long. So periods 1-48 are always requested together, and on that one day a
    second request covers periods 49-50.
    """
    params = {"from": settlement_date, "to": settlement_date, "format": "json"}
    if periods_in_day(settlement_date) == 50:
        download_to_cache("datasets/BOALF", params | {"settlementPeriodFrom": 49, "settlementPeriodTo": 50},
                          boalf_late_cache_path(settlement_date))
    return download_to_cache("datasets/BOALF", params | {"settlementPeriodFrom": 1, "settlementPeriodTo": 48},
                             boalf_cache_path(settlement_date))


def acceptances_cache_path(settlement_date: str, settlement_period: int) -> Path:
    return RAW_DIR / "ACCEPTANCES" / f"ACCEPTANCES_{settlement_date}_SP{settlement_period:02d}.json.gz"


def fetch_acceptances_period(settlement_date: str, settlement_period: int) -> Path:
    """Every accepted bid and offer in one period, with its price (ISPSTACK / BOALF / BOD).

    Only available per period, so used for hand-checking rather than bulk totals.
    """
    endpoint = f"balancing/settlement/acceptances/all/{settlement_date}/{settlement_period}"
    path = acceptances_cache_path(settlement_date, settlement_period)
    return download_to_cache(endpoint, {"format": "json"}, path)


# --- Reference data ----------------------------------------------------------------------

def bmunits_cache_path() -> Path:
    return RAW_DIR / "reference" / "bmunits_all.json.gz"


def fetch_bmunits() -> Path:
    """The BM unit register: one record per unit, with fuel type and lead party."""
    return download_to_cache("reference/bmunits/all", {}, bmunits_cache_path())


# NESO data portal resources, by CKAN resource id
TEC_REGISTER_ID = "17becbab-e3e8-473f-b303-3806f43a6a10"


CONSTRAINT_BREAKDOWN_IDS = {  # NESO "Constraint Breakdown Costs and Volume", by financial year
    "2023-24": "24d067d8-1328-452a-9720-21cb691e491e",
    "2024-25": "748557ef-2bb3-41c0-8181-5f1a148c1ff4",
    "2025-26": "6afe1c2b-6d70-4e76-8e74-0952b0a2beab",
}


def constraint_breakdown_cache_path(financial_year: str) -> Path:
    return RAW_DIR / "neso" / f"constraint_breakdown_{financial_year}.csv.gz"


def fetch_constraint_breakdown(financial_year: str) -> Path:
    """NESO's published daily constraint costs and volumes, split by constraint type.
    Used only to reconcile our bottom-up totals."""
    resource_id = CONSTRAINT_BREAKDOWN_IDS[financial_year]
    return download_to_cache(f"datastore/dump/{resource_id}", {},
                             constraint_breakdown_cache_path(financial_year), base=NESO_URL)


def tec_register_cache_path() -> Path:
    return RAW_DIR / "neso" / "tec_register.csv.gz"


def fetch_tec_register() -> Path:
    """NESO's Transmission Entry Capacity register: every transmission-connected project,
    with its connection site and host transmission owner. A current snapshot, not history."""
    return download_to_cache(f"datastore/dump/{TEC_REGISTER_ID}", {}, tec_register_cache_path(), base=NESO_URL)


def keep_windows_awake() -> None:
    """Ask Windows not to sleep from inactivity while this script runs.

    Only affects this process: the request ends when the script exits, and no power
    settings are changed. (Closing the lid can still put the machine to sleep.)
    """
    if sys.platform == "win32":
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def daily_datasets(settlement_date: str) -> list[tuple]:
    """Every per-day download, as (fetch function, its arguments, its cache path)."""
    d = settlement_date
    jobs = [(fetch_mid_day, (d,), mid_cache_path(d)), (fetch_boalf_day, (d,), boalf_cache_path(d))]
    for side in ["bid", "offer"]:
        jobs.append((fetch_cashflows_day, (d, side), cashflow_cache_path(d, side)))
        jobs.append((fetch_boav_day, (d, side), boav_cache_path(d, side)))
    return jobs


def fetch_day(settlement_date: str) -> list[str]:
    """Cache every daily dataset for one date. Returns the names of any that failed."""
    downloaded, failed = 0, []
    for fetch, args, path in daily_datasets(settlement_date):
        if path.exists():
            continue
        try:
            fetch(*args)
            downloaded += 1
        except Exception as error:  # keep going; a re-run retries whatever is missing
            failed.append(path.name)
            print(f"  FAILED {path.name}: {error}")
    print(f"{settlement_date}: {downloaded} downloaded, {len(failed)} failed", flush=True)
    return failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache Elexon data for one date or a range of dates.")
    parser.add_argument("start", help="settlement date, YYYY-MM-DD")
    parser.add_argument("end", nargs="?", help="last settlement date of a range (inclusive)")
    parser.add_argument("--period", type=int, help="also cache acceptance detail for this period")
    args = parser.parse_args()

    keep_windows_awake()
    fetch_bmunits()
    fetch_tec_register()
    for financial_year in CONSTRAINT_BREAKDOWN_IDS:
        fetch_constraint_breakdown(financial_year)
    dates = pd.date_range(args.start, args.end or args.start).strftime("%Y-%m-%d")
    failures = [name for d in dates for name in fetch_day(d)]
    if args.period:
        fetch_acceptances_period(args.start, args.period)

    print(f"\nDone: {len(dates)} dates, {len(failures)} failed downloads"
          + (" (re-run the same command to retry them)" if failures else ""))
