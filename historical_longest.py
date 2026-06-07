#!/usr/bin/env python3
"""
Compute the longest-named GOALSCORERS from recent tournaments, straight from
openfootball's public data (no API key). Applies the same name-length rule as
longest_names.py. Prints a ranked list and writes out/historical_longest.csv.
"""
import csv
import json
import urllib.request
from pathlib import Path

from longest_names_wiki import name_letters

OUT = Path(__file__).parent / "out"
SOURCES = {
    "WC 2018": "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2018/worldcup.json",
    "WC 2022": "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2022/worldcup.json",
    "Euro 2020": "https://raw.githubusercontent.com/openfootball/euro.json/master/2020/euro.json",
    "Euro 2024": "https://raw.githubusercontent.com/openfootball/euro.json/master/2024/euro.json",
}


def main():
    OUT.mkdir(exist_ok=True)
    best = {}  # player name -> (letters, tournament)
    for tour, url in SOURCES.items():
        try:
            data = json.load(urllib.request.urlopen(url, timeout=30))
        except Exception as e:
            print(f"  skip {tour}: {e}")
            continue
        n = 0
        for m in data.get("matches", []):
            for key in ("goals1", "goals2", "goals"):
                for g in m.get(key) or []:
                    if not isinstance(g, dict) or g.get("owngoal"):
                        continue
                    nm = g.get("name")
                    if not nm:
                        continue
                    n += 1
                    letters, _ = name_letters(nm)
                    if nm not in best or letters > best[nm][0]:
                        best[nm] = (letters, tour)
        print(f"  {tour}: {n} goals parsed")

    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    with open(OUT / "historical_longest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["letters", "player", "tournament"])
        for nm, (letters, tour) in ranked:
            w.writerow([letters, nm, tour])

    print(f"\nLongest-named goalscorers, last tournaments ({len(ranked)} scorers):")
    for nm, (letters, tour) in ranked[:20]:
        print(f"  {letters:>2}  {nm}  ({tour})")
    print(f"\nFull list -> {OUT/'historical_longest.csv'}")


if __name__ == "__main__":
    main()
