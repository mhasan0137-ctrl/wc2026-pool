#!/usr/bin/env python3
"""
Rank every player in the 48 WC 2026 squads by name length, using the pool rule:
  first name + last name only, double-barrelled (hyphenated) names count in full,
  spaces and hyphens don't count, accented letters do.

Needs the free API-Football key:  export API_FOOTBALL_KEY=...
(48 squads = ~49 calls; the free tier allows 100/day, ~10/min, so we throttle.)

    python3 longest_names.py        # prints top 40, writes out/longest_names.csv
"""

import csv
import os
import sys
import time
import unicodedata
import urllib.request
import json
from pathlib import Path

BASE = "https://v3.football.api-sports.io"
WC_LEAGUE_ID, WC_SEASON = 1, 2026
OUT = Path(__file__).parent / "out"


def call(path, **params):
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("Set API_FOOTBALL_KEY first (free key from api-football.com).")
    q = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{q}", headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("response", [])


# Surname particles that ARE part of the surname (so they count), as opposed to
# standalone middle names (which don't). e.g. "Kevin De Bruyne" -> Kevin + De Bruyne,
# but "Carlos Henrique Casimiro" -> Carlos + Casimiro (middle name Henrique dropped).
PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da", "das",
             "dos", "do", "du", "le", "la", "mac", "mc", "st", "bin", "ibn", "al",
             "ter", "ten", "op", "te", "vande", "vander"}


def name_letters(full_name):
    """
    Letters in first name + surname. Surname = last token plus any immediately
    preceding particle tokens (De, van, Mac...). Standalone middle names are dropped.
    Hyphenated double-barrels (Alexander-Arnold) are one token and count in full.
    """
    tokens = full_name.split()
    if not tokens:
        return 0, full_name
    if len(tokens) == 1:
        relevant = tokens
    else:
        surname = [tokens[-1]]
        i = len(tokens) - 2
        while i >= 1 and tokens[i].lower().strip(".'`") in PARTICLES:
            surname.insert(0, tokens[i])
            i -= 1
        relevant = [tokens[0]] + surname          # first name + (particles +) surname
    letters = sum(1 for ch in "".join(relevant) if unicodedata.category(ch).startswith("L"))
    return letters, full_name


def main():
    OUT.mkdir(exist_ok=True)
    print("Fetching the 48 WC 2026 teams ...")
    teams = call("teams", league=WC_LEAGUE_ID, season=WC_SEASON)
    rows = []
    for i, t in enumerate(teams, 1):
        team = t["team"]
        print(f"  [{i}/{len(teams)}] squad: {team['name']}")
        for squad in call("players/squads", team=team["id"]):
            for p in squad.get("players", []):
                letters, name = name_letters(p["name"])
                rows.append({"letters": letters, "player": name,
                             "position": p.get("position", "?"), "team": team["name"]})
        time.sleep(7)  # stay under the free-tier ~10 req/min ceiling

    rows.sort(key=lambda r: -r["letters"])
    with open(OUT / "longest_names.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["letters", "player", "position", "team"])
        for r in rows:
            w.writerow([r["letters"], r["player"], r["position"], r["team"]])

    print(f"\nTop 40 longest names ({len(rows)} players total):")
    print(f"{'#':>3}  {'letters':>7}  {'pos':<4} player (team)")
    for r in rows[:40]:
        print(f"{rows.index(r)+1:>3}  {r['letters']:>7}  {r['position'][:4]:<4} "
              f"{r['player']} ({r['team']})")
    print(f"\nFull ranking -> {OUT/'longest_names.csv'}")


if __name__ == "__main__":
    main()
