"""Download raw data from the Elexon Insights API and cache it, unchanged, in data/raw/.

Run from the project root, one settlement date at a time:
    python src/fetch.py 2024-04-07                    # every daily dataset for that date
    python src/fetch.py 2024-04-07 --period 23        # also the acceptance detail for period 23

No API key is needed. Files already in the cache are never re-requested.
"""

import argparse
import gzip
from pathlib import Path

import requests

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
NESO_URL = "https://api.neso.energy"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def download_to_cache(endpoint: str, params: dict, path: Path, base: str = BASE_URL) -> Path:
    """GET one endpoint and save the response bytes to `path`, unless already cached."""
    if path.exists():
        print(f"Already cached, not re-requesting: {path.name}")
        return path

    response = requests.get(f"{base}/{endpoint}", params=params, timeout=120)
    response.raise_for_status()

    # Save the bytes exactly as received, gzip-compressed (JSON shrinks ~10x, and
    # decompressing gives back the identical bytes). All parsing happens later, from this file.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(response.content))
    print(f"Saved {len(response.content):,} bytes to {path.relative_to(RAW_DIR.parent.parent)}")
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


def fetch_boalf_day(settlement_date: str) -> Path:
    """Every bid-offer acceptance for one settlement day, with its system (soFlag) flag."""
    params = {
        "from": settlement_date,
        "to": settlement_date,
        "settlementPeriodFrom": 1,
        "settlementPeriodTo": 50,
        "format": "json",
    }
    return download_to_cache("datasets/BOALF", params, boalf_cache_path(settlement_date))


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


def tec_register_cache_path() -> Path:
    return RAW_DIR / "neso" / "tec_register.csv.gz"


def fetch_tec_register() -> Path:
    """NESO's Transmission Entry Capacity register: every transmission-connected project,
    with its connection site and host transmission owner. A current snapshot, not history."""
    return download_to_cache(f"datastore/dump/{TEC_REGISTER_ID}", {}, tec_register_cache_path(), base=NESO_URL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache one settlement day of Elexon data.")
    parser.add_argument("settlement_date", help="settlement date, YYYY-MM-DD")
    parser.add_argument("--period", type=int, help="also cache acceptance detail for this period")
    args = parser.parse_args()

    fetch_mid_day(args.settlement_date)
    for side in ["bid", "offer"]:
        fetch_cashflows_day(args.settlement_date, side)
        fetch_boav_day(args.settlement_date, side)
    fetch_boalf_day(args.settlement_date)
    fetch_bmunits()
    fetch_tec_register()
    if args.period:
        fetch_acceptances_period(args.settlement_date, args.period)
