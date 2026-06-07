#!/usr/bin/env python3
"""
Longest-named players in the 2026 World Cup squads — scraped from Wikipedia's
"2026 FIFA World Cup squads" page (no API key). Applies the pool name rule.
Writes out/longest_names.csv (the guide auto-displays its top 10).

    python3 longest_names_wiki.py
"""
import csv
import re
import urllib.request
from pathlib import Path

from longest_names import name_letters

OUT = Path(__file__).parent / "out"
WIKI = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads?action=raw"


def scrape():
    req = urllib.request.Request(WIKI, headers={"User-Agent": "wc2026-pool-script"})
    txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    team, rows = None, []
    for line in txt.splitlines():
        head = re.match(r"^===\s*([^=].*?)\s*===\s*$", line)
        if head:
            team = head.group(1).strip()
            continue
        if "nat fs g player" not in line:
            continue
        nm = re.search(r"name=\[\[([^\]]+)\]\]", line)
        if not nm:
            continue
        name = nm.group(1).split("|")[-1].strip()   # [[Link|Display]] -> Display
        pos = re.search(r"pos=([A-Za-z]{2})", line)
        letters, _ = name_letters(name)
        rows.append((letters, name, pos.group(1) if pos else "?", team))
    rows.sort(key=lambda r: -r[0])
    return rows


def main():
    OUT.mkdir(exist_ok=True)
    rows = scrape()
    with open(OUT / "longest_names.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["letters", "player", "position", "team"])
        w.writerows(rows)
    print(f"Scraped {len(rows)} players. Top 15 longest names:")
    for letters, name, pos, team in rows[:15]:
        print(f"  {letters:>2}  {pos:<3} {name} ({team})")
    print(f"\nFull ranking -> {OUT/'longest_names.csv'}")


if __name__ == "__main__":
    main()
