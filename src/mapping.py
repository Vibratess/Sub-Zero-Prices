"""Map each wind BM unit to the side of the grid it connects on.

Run from the project root (after src/fetch.py has cached the BM unit register and TEC register):
    python src/mapping.py

Two committed CSVs hold every decision, so a reader can audit them:

  data/wind_site_matches.csv   one row per transmission-connected wind site: the TEC register
                               project it was matched to and the host transmission owner.
                               Rows are proposed by name matching, then reviewed by hand;
                               a reviewed row is never overwritten.
  data/bmunit_map.csv          the output: one row per wind BM unit, with region and the
                               method used. This is what the analysis reads.

Region rules:
  - Embedded units carry a GSP group in Elexon's register (the distribution area they sit in).
    North Scotland is in SHET's transmission area and South Scotland in SPT's.
  - Transmission units take the HOST TO of their matched TEC register project:
    SHET or SPT = Scotland, NGET = England & Wales. Offshore wind on an offshore transmission
    owner (OFTO) link is resolved by hand, with the reason written in the evidence column.
"""

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from fetch import bmunits_cache_path, tec_register_cache_path
from parse import parse_bmunits

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SITE_MATCHES = DATA_DIR / "wind_site_matches.csv"
BMUNIT_MAP = DATA_DIR / "bmunit_map.csv"

HOST_TO_REGION = {"SHET": "Scotland", "SPT": "Scotland", "NGET": "England & Wales"}
GSP_GROUP_HOST_TO = {"North Scotland": "SHET", "South Scotland": "SPT"}  # every other group: NGET

# Words that say nothing about which wind farm a name refers to
FILLER = {"wind", "farm", "wf", "owf", "offshore", "onshore", "bmu", "unit", "ltd", "limited",
          "plc", "the", "energy", "power", "generation", "project", "renewables", "t"}
NAME_SCORE_FLOOR = 0.75  # below this, a unit's own name is too uninformative to match on


def normalise(name: str) -> str:
    """Lower-case, strip punctuation, unit numbers and filler words: 'Seagreen1 Offshore WF 1' -> 'seagreen1'."""
    text = re.sub(r"[^a-z0-9 ]", " ", str(name).lower().replace("windfarm", "wind farm"))
    return " ".join(t for t in text.split() if t not in FILLER and not t.isdigit())


def similarity(a: str, b: str) -> float:
    """0-1 similarity of two normalised names."""
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def best_tec_match(site_name: str, lead_party: str, tec: pd.DataFrame) -> tuple[pd.Series, float, str]:
    """The TEC project that best matches a wind site, its score, and what was matched on.

    The unit's own name is tried first. Only if that is uninformative (often it is just a
    code such as 'T_INCWO-1') does the company name get used: one company owns many wind
    farms, so matching on it alone can pick the wrong one.
    """
    by_name = tec["n_project"].map(lambda p: similarity(normalise(site_name), p))
    if by_name.max() >= NAME_SCORE_FLOOR:
        scores, basis = by_name, "unit name"
    else:
        scores = tec["n_customer"].map(lambda c: similarity(normalise(lead_party), c))
        scores = scores.combine(tec["n_project"].map(lambda p: similarity(normalise(lead_party), p)), max)
        basis = "lead party name"
    # Among equal scores, prefer a project that is already built
    ranked = tec.assign(score=scores, built=tec["Project Status"].eq("Built")).sort_values(
        ["score", "built"], ascending=False)
    best = ranked.iloc[0]
    return best, round(float(best["score"]), 2), basis


def load_tec_wind() -> pd.DataFrame:
    tec = pd.read_csv(tec_register_cache_path())
    tec = tec[tec["Plant Type"].str.contains("Wind", case=False, na=False)].copy()
    tec["n_project"] = tec["Project Name"].map(normalise)
    tec["n_customer"] = tec["Customer Name"].map(normalise)
    return tec


def wind_units() -> pd.DataFrame:
    units = parse_bmunits(bmunits_cache_path())
    wind = units[units["fuel_type"] == "WIND"].copy()
    wind["site"] = wind["ng_bm_unit"].str.split("-").str[0]  # 'SGRWO-6' -> 'SGRWO'
    return wind


def update_site_matches(wind: pd.DataFrame, tec: pd.DataFrame) -> pd.DataFrame:
    """Propose TEC matches for transmission sites not yet in wind_site_matches.csv.

    Existing rows are kept exactly as they are, so hand-reviewed decisions survive re-runs.
    """
    existing = pd.read_csv(SITE_MATCHES, dtype=str) if SITE_MATCHES.exists() else pd.DataFrame(
        columns=["site", "unit_name", "tec_project", "host_to", "score", "matched_on", "reviewed", "evidence"])

    transmission = wind[wind["gsp_group"].isna()]
    sites = transmission.groupby("site").agg(unit_name=("name", "first"), lead_party=("lead_party", "first"))
    new_rows = []
    for site, s in sites.drop(existing["site"], errors="ignore").iterrows():
        best, score, basis = best_tec_match(s["unit_name"], s["lead_party"], tec)
        new_rows.append({
            "site": site, "unit_name": s["unit_name"], "tec_project": best["Project Name"],
            "host_to": best["HOST TO"], "score": score, "matched_on": basis,
            "reviewed": "no", "evidence": f"TEC register: {best['Project Name']} ({best['Connection Site']})",
        })
    if new_rows:
        print(f"{len(new_rows)} new sites proposed; set reviewed=yes in {SITE_MATCHES.name} once checked")
    matches = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True).sort_values("site")
    matches.to_csv(SITE_MATCHES, index=False)
    return matches


def build_bmunit_map(wind: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """One row per wind BM unit with its host transmission owner, region and method."""
    out = wind[["bm_unit", "ng_bm_unit", "site", "name", "fuel_type", "gsp_group",
                "generation_capacity_mw"]].copy()

    embedded = out["gsp_group"].notna()
    out.loc[embedded, "host_to"] = out.loc[embedded, "gsp_group"].map(GSP_GROUP_HOST_TO).fillna("NGET")
    out.loc[embedded, "method"] = "register GSP group: " + out.loc[embedded, "gsp_group"]

    site_lookup = matches.set_index("site")
    trans = ~embedded
    out.loc[trans, "host_to"] = out.loc[trans, "site"].map(site_lookup["host_to"])
    out.loc[trans, "method"] = out.loc[trans, "site"].map(
        site_lookup["evidence"] + " [reviewed: " + site_lookup["reviewed"] + "]")

    out["region"] = out["host_to"].map(HOST_TO_REGION).fillna("Unresolved")
    return out.drop(columns="gsp_group").sort_values("bm_unit")


if __name__ == "__main__":
    wind = wind_units()
    matches = update_site_matches(wind, load_tec_wind())
    bmunit_map = build_bmunit_map(wind, matches)
    bmunit_map.to_csv(BMUNIT_MAP, index=False)

    summary = bmunit_map.groupby("region")["generation_capacity_mw"].agg(["count", "sum"]).round(0)
    print(summary.rename(columns={"count": "units", "sum": "capacity_mw"}).to_string())
    unreviewed = (matches["reviewed"] != "yes").sum()
    print(f"Wrote {BMUNIT_MAP.name}: {len(bmunit_map)} wind units; {unreviewed} site matches not yet reviewed")
