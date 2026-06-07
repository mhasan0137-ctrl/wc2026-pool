#!/usr/bin/env python3
"""
World Cup 2026 office-pool tracker.

Two data sources, pick based on what you've got:

  1. openfootball (default)  -- no API key, no signup, no rate limit.
     Gives you fixtures + results + (where available) goal scorers.
     Community-updated, so results can lag a few hours/a day. Perfect
     for a pool that's settled after the final.

  2. API-Football            -- free key (100 calls/day) from
     https://www.api-football.com/. More timely, has a clean
     top-scorers endpoint and full 26-man squads. Turn it on by:
         export API_FOOTBALL_KEY=your_key_here

Run:
    python3 wc_tracker.py              # openfootball aggregates -> ./out/
    python3 wc_tracker.py --players    # also fetch player goals (needs key)

Outputs CSVs + a printed summary tuned to the tote questions
(total goals, 5+ goal games, highest-scoring match, penalties, etc).

Stdlib only -- nothing to pip install.
"""

import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
WC_LEAGUE_ID = 1      # FIFA World Cup in API-Football
WC_SEASON = 2026

OUT = Path(__file__).parent / "out"


# --------------------------------------------------------------------------
# fetch helpers
# --------------------------------------------------------------------------
def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def api_football(path, **params):
    """Call API-Football; returns the 'response' list. Needs API_FOOTBALL_KEY."""
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("Set API_FOOTBALL_KEY to use the --players / API-Football features.")
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_FOOTBALL_BASE}/{path}?{q}"
    return _get(url, headers={"x-apisports-key": key}).get("response", [])


# --------------------------------------------------------------------------
# openfootball: fixtures, results, tournament aggregates
# --------------------------------------------------------------------------
def load_openfootball():
    return _get(OPENFOOTBALL_URL)["matches"]


def is_played(m):
    """A match is played once openfootball has filled in a full-time score."""
    return isinstance(m.get("score"), dict) and "ft" in m["score"]


def parse_scorers(match):
    """
    Best-effort scorer extraction. openfootball uses a few shapes across
    repos/years; we tolerate 'goals1'/'goals2' and a combined 'goals'.
    Returns list of (player_name, team_name).
    """
    out = []
    for key, team in (("goals1", match["team1"]), ("goals2", match["team2"])):
        for g in match.get(key, []) or []:
            name = g.get("name") if isinstance(g, dict) else None
            if name and not (isinstance(g, dict) and g.get("owngoal")):
                out.append((name, team))
    for g in match.get("goals", []) or []:        # combined-array fallback
        if isinstance(g, dict) and g.get("name") and not g.get("owngoal"):
            out.append((g["name"], g.get("team", "?")))
    return out


def aggregate(matches):
    played = [m for m in matches if is_played(m)]
    total_goals = 0
    high = {"goals": -1, "match": None}
    five_plus = []
    team_for = defaultdict(int)
    team_against = defaultdict(int)
    scorers = defaultdict(int)
    pen_shootouts = []

    for m in played:
        a, b = m["score"]["ft"]
        g = a + b
        total_goals += g
        team_for[m["team1"]] += a
        team_for[m["team2"]] += b
        team_against[m["team1"]] += b
        team_against[m["team2"]] += a
        if g > high["goals"]:
            high = {"goals": g, "match": f'{m["team1"]} {a}-{b} {m["team2"]}'}
        if g >= 5:
            five_plus.append(f'{m["team1"]} {a}-{b} {m["team2"]}')
        # penalty shootout: openfootball stores a 'pen' (or 'p') key alongside 'ft'
        if "pen" in m["score"] or "p" in m["score"]:
            pen_shootouts.append(f'{m["team1"]} v {m["team2"]} ({m.get("round","?")})')
        for name, team in parse_scorers(m):
            scorers[(name, team)] += 1

    return {
        "matches_played": len(played),
        "matches_total": len(matches),
        "total_goals": total_goals,
        "avg_goals_per_match": round(total_goals / len(played), 2) if played else 0,
        "highest_scoring": high,
        "five_plus_games": five_plus,
        "penalty_shootouts": pen_shootouts,
        "team_for": dict(team_for),
        "team_against": dict(team_against),
        "scorers": scorers,
    }


# --------------------------------------------------------------------------
# API-Football: full squads + authoritative top scorers + red cards
# --------------------------------------------------------------------------
def fetch_players():
    print("Fetching top scorers from API-Football ...")
    rows = api_football("players/topscorers", league=WC_LEAGUE_ID, season=WC_SEASON)
    players = []
    for r in rows:
        p = r["player"]
        s = r["statistics"][0]
        players.append({
            "player": p["name"],
            "team": s["team"]["name"],
            "goals": (s["goals"]["total"] or 0),
            "assists": (s["goals"]["assists"] or 0),
            "minutes": (s["games"]["minutes"] or 0),
            "yellow": (s["cards"]["yellow"] or 0),
            "red": (s["cards"]["red"] or 0),
        })
    return players


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def write_csv(path, rows, header):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_html(agg, players):
    """Render a single self-contained index.html for GitHub Pages."""
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    h = agg["highest_scoring"]
    team_rows = sorted(
        ({"t": t, "f": agg["team_for"].get(t, 0), "a": agg["team_against"].get(t, 0)}
         for t in set(agg["team_for"]) | set(agg["team_against"])),
        key=lambda r: (-r["f"], r["a"]),
    )
    scorer_src = (
        [(p["player"], p["team"], p["goals"]) for p in players[:15]]
        if players else
        [(n, t, g) for (n, t), g in
         sorted(agg["scorers"].items(), key=lambda kv: -kv[1])[:15]]
    )

    def rows(items, cells):
        return "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in cells(x))
                         + "</tr>" for x in items)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Office Pool</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} .sub{{color:#666;margin-top:0}}
 .cards{{display:flex;flex-wrap:wrap;gap:1rem;margin:1.5rem 0}}
 .card{{flex:1 1 160px;background:#f4f6f8;border-radius:10px;padding:1rem}}
 .card .n{{font-size:1.8rem;font-weight:700}} .card .l{{color:#666;font-size:.85rem}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0 2rem}}
 th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e3e6ea}}
 th{{background:#fafbfc}} td:not(:first-child){{text-align:right}}
 a{{color:#2563eb}}
</style></head><body>
<h1>⚽ WC 2026 Office Pool</h1>
<p class="sub">Auto-updated {updated} · {agg['matches_played']}/{agg['matches_total']} matches played</p>
<div class="cards">
 <div class="card"><div class="n">{agg['total_goals']}</div><div class="l">Total goals (avg {agg['avg_goals_per_match']}/match)</div></div>
 <div class="card"><div class="n">{len(agg['five_plus_games'])}</div><div class="l">Games with 5+ goals</div></div>
 <div class="card"><div class="n">{len(agg['penalty_shootouts'])}</div><div class="l">Penalty shootouts</div></div>
 <div class="card"><div class="n">{h['goals'] if h['match'] else 0}</div><div class="l">Highest match: {h['match'] or '—'}</div></div>
</div>
<h2>Top scorers</h2>
<table><tr><th>Player</th><th>Team</th><th>Goals</th></tr>
{rows(scorer_src, lambda x: (x[0], x[1], x[2]))}
</table>
<h2>Goals by team</h2>
<table><tr><th>Team</th><th>For</th><th>Against</th></tr>
{rows(team_rows, lambda r: (r['t'], r['f'], r['a']))}
</table>
<p><a href="fixtures.csv">fixtures.csv</a> · <a href="team_goals.csv">team_goals.csv</a> · <a href="scorers_openfootball.csv">scorers.csv</a></p>
</body></html>"""
    (OUT / "index.html").write_text(html)


def main():
    OUT.mkdir(exist_ok=True)
    want_players = "--players" in sys.argv

    matches = load_openfootball()
    agg = aggregate(matches)

    # fixtures.csv -- everything, played or not
    write_csv(
        OUT / "fixtures.csv",
        [[m.get("round", ""), m.get("date", ""), m.get("group", ""),
          m["team1"], m["team2"],
          (m["score"]["ft"][0] if is_played(m) else ""),
          (m["score"]["ft"][1] if is_played(m) else "")]
         for m in matches],
        ["round", "date", "group", "team1", "team2", "score1", "score2"],
    )

    # team_goals.csv -- handy for the sweepstake (whose drawn country is scoring)
    teams = sorted(set(agg["team_for"]) | set(agg["team_against"]))
    write_csv(
        OUT / "team_goals.csv",
        [[t, agg["team_for"].get(t, 0), agg["team_against"].get(t, 0)] for t in teams],
        ["team", "goals_for", "goals_against"],
    )

    # scorers from openfootball (best-effort)
    sc = sorted(agg["scorers"].items(), key=lambda kv: -kv[1])
    write_csv(
        OUT / "scorers_openfootball.csv",
        [[name, team, n] for (name, team), n in sc],
        ["player", "team", "goals"],
    )

    # ---- summary tuned to the tote questions ----
    print("\n=== WC 2026 pool tracker ===")
    print(f"Matches played: {agg['matches_played']}/{agg['matches_total']}")
    print(f"TOTAL GOALS so far: {agg['total_goals']}  (avg {agg['avg_goals_per_match']}/match)")
    if agg["highest_scoring"]["match"]:
        h = agg["highest_scoring"]
        print(f"Highest-scoring match: {h['match']}  ({h['goals']} goals)")
    print(f"Games with 5+ goals: {len(agg['five_plus_games'])}  {agg['five_plus_games']}")
    print(f"Penalty shootouts: {agg['penalty_shootouts'] or 'none yet'}")
    if sc:
        print("Top scorers (openfootball, best-effort):")
        for (name, team), n in sc[:10]:
            print(f"   {n:>2}  {name} ({team})")

    players = []
    if want_players and not os.environ.get("API_FOOTBALL_KEY"):
        print("\n--players requested but API_FOOTBALL_KEY not set — skipping "
              "player fetch, using openfootball scorers instead.")
        want_players = False
    if want_players:
        players = fetch_players()
        players.sort(key=lambda p: (-p["goals"], -p["assists"]))
        write_csv(
            OUT / "players_apifootball.csv",
            [[p["player"], p["team"], p["goals"], p["assists"],
              p["minutes"], p["yellow"], p["red"]] for p in players],
            ["player", "team", "goals", "assists", "minutes", "yellow", "red"],
        )
        total_reds = sum(p["red"] for p in players)
        print(f"\nAPI-Football: {len(players)} players, total red cards (from "
              f"scorers list — not all players): {total_reds}")
        print("   -> wrote players_apifootball.csv")

    write_html(agg, players)
    print(f"\nWrote CSVs + index.html to {OUT}/")


if __name__ == "__main__":
    main()
