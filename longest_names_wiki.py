#!/usr/bin/env python3
"""
Longest-named players in the 2026 World Cup squads — scraped from Wikipedia's
"2026 FIFA World Cup squads" page (no API key). Applies the pool name rule.
Writes out/longest_names.csv (the guide auto-displays its top 10).

    python3 longest_names_wiki.py
"""
import csv
import re
import unicodedata
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "out"
WIKI = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads?action=raw"

# Surname particles that count as part of the surname (De, van, Mac…), so a name
# like "Kevin De Bruyne" -> Kevin + De Bruyne; standalone middle names are dropped.
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


def scrape():
    """Return one dict per squad player: name, pos, team, letters, born (y,m,d)|None."""
    req = urllib.request.Request(WIKI, headers={"User-Agent": "wc2026-pool-script"})
    txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    team, players = None, []
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
        # birth date and age2|<ref y>|<ref m>|<ref d>|<born y>|<born m>|<born d>
        bd = re.search(r"birth date and age2\|\d+\|\d+\|\d+\|(\d+)\|(\d+)\|(\d+)", line)
        letters, _ = name_letters(name)
        players.append({
            "name": name, "pos": pos.group(1) if pos else "?", "team": team,
            "letters": letters,
            "born": (int(bd.group(1)), int(bd.group(2)), int(bd.group(3))) if bd else None,
        })
    return players


def longest(players):
    rows = [(p["letters"], p["name"], p["pos"], p["team"]) for p in players]
    rows.sort(key=lambda r: -r[0])
    return rows


def main():
    OUT.mkdir(exist_ok=True)
    rows = longest(scrape())
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
