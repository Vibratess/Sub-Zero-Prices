"""Download raw data from the Elexon Insights API and cache it, unchanged, in data/raw/.

Run from the project root, one settlement date at a time:
    python src/fetch.py 2024-04-07

No API key is needed. Files already in the cache are never re-requested.
"""

import argparse
from pathlib import Path

import requests

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def mid_cache_path(settlement_date: str) -> Path:
    """Where the raw Market Index Data response for one settlement date is stored."""
    return RAW_DIR / "MID" / f"MID_{settlement_date}.json"


def fetch_mid_day(settlement_date: str) -> Path:
    """Download one settlement day of Market Index Data (MID) and save the raw JSON.

    Returns the cache path. If the file already exists, nothing is requested.
    """
    path = mid_cache_path(settlement_date)
    if path.exists():
        print(f"Already cached, not re-requesting: {path.name}")
        return path

    # When settlementPeriodFrom/To are given, the API reads from/to as settlement
    # dates rather than timestamps. Period 50 covers the long autumn clock-change day.
    params = {
        "from": settlement_date,
        "to": settlement_date,
        "settlementPeriodFrom": 1,
        "settlementPeriodTo": 50,
        "format": "json",
    }
    response = requests.get(f"{BASE_URL}/datasets/MID", params=params, timeout=60)
    response.raise_for_status()

    # Save the bytes exactly as received. All parsing happens later, from this file.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    print(f"Saved {len(response.content):,} bytes to {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache one settlement day of Elexon MID data.")
    parser.add_argument("settlement_date", help="settlement date, YYYY-MM-DD")
    args = parser.parse_args()
    fetch_mid_day(args.settlement_date)
