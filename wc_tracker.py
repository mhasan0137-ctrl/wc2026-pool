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


# Static historical helper notes, one per pool question. Pure reference — these
# don't change during the tournament, they just help people calibrate guesses.
# All totals carry the BIG caveat: 2026 has 104 matches vs 64 in past World Cups.
QUESTION_GUIDE = [
    ("1. Longest-named goalscorer (letters)",
     "First + last name only; double-barrels count, spaces/hyphens don't. "
     "Trent Alexander-Arnold = 20. Squad maxes run into the mid-20s, but only "
     "<i>goalscorers</i> count — so a regular striker with a long name is the real ceiling. "
     "Run longest_names.py (needs the API key) for the exact squad ranking."),
    ("2. Own goals in the tournament",
     "Wildly swingy: WC 2018 = <b>12</b> (record), WC 2022 = <b>2</b>; Euro 2020 = 11, Euro 2024 = 10. "
     "No safe number. Scaled to 104 games, ~<b>8–14</b> is a sane band."),
    ("3. Red cards in the tournament",
     "VAR era is low: WC 2018 = <b>4</b>, 2022 = <b>4</b> (vs 2010 = 17, 2014 = 10); Euro 2024 = 6. "
     "Per-match rate × 104 games → ~<b>6–10</b>."),
    ("4. Penalty shootouts",
     "WC 2018 = <b>4</b>, 2022 = <b>5</b> (record); Euro 2020 = 4. 2026 adds a Round of 32, so there are "
     "<b>32 knockout games vs 16</b> before — double the shootout chances. Think ~<b>6–9</b>."),
    ("5. Goals in the final",
     "Total coin-flip: 2010 = 1, 2014 = 1, 2018 = <b>6</b>, 2022 = <b>6</b> (incl. extra time). Range 1–6."),
    ("6. Winning continent",
     "Only <b>Europe</b> and <b>South America</b> have <i>ever</i> won a World Cup. "
     "“Other” has literally never happened — so it pays huge if it ever does."),
    ("7. Highest-scoring 10-minute bracket",
     "Historically the <b>final 10 minutes (76–90+)</b> score the most — tiring legs + stoppage time. "
     "It's the favourite, so the tote pays little; a contrarian early bracket pays big if it lands."),
    ("8. Top goalscorer (Golden Boot)",
     "Recent tallies: 2010 = 5, 2014 = 6, 2018 = 6, 2022 = <b>8</b>. The 2026 winner can play <b>8</b> games "
     "(extra round), so expect ~<b>7–9</b> goals to win it."),
    ("9. Group with fewest total goals",
     "12 groups of 4 (six games each). Defensive / 'group of death' style groups bottom out low; "
     "watch for a group stacked with cagey teams."),
    ("10. Youngest goalscorer (age)",
     "2022: Gavi <b>18y 110d</b>. All-time record: Pelé <b>17y 239d</b> (1958) — the only sub-18 scorer ever. "
     "Expect a youngest scorer around <b>18</b>; anything under that is historic."),
    ("11. Will a goalkeeper score?",
     "<b>No keeper has ever scored in men's senior World Cup history.</b> So 'No' is the heavy favourite "
     "and pays peanuts — which is exactly why a 'Yes' would pay a fortune."),
    ("12. Pick a scoreline that happens exactly once",
     "Common scorelines (1–0, 2–1, 1–1) recur many times; rarer ones (4–3, 5–2, 3–3) often happen "
     "0 or 1 times. The sweet spot is a scoreline plausible enough to occur, rare enough to occur only once."),
]


def write_guide():
    """Render guide.html — static helpful stats for every pool question."""
    blocks = "\n".join(
        f'<div class="q"><h3>{title}</h3><p>{body}</p></div>'
        for title, body in QUESTION_GUIDE
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Pool — Question Guide</title>
<style>
 body{{font:15px/1.6 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} .sub{{color:#666;margin-top:0}}
 .warn{{background:#fff6e5;border:1px solid #ffd58a;border-radius:8px;padding:.8rem 1rem;margin:1rem 0}}
 .q{{border-bottom:1px solid #e3e6ea;padding:.7rem 0}} .q h3{{margin:.2rem 0;font-size:1.05rem}}
 .q p{{margin:.3rem 0;color:#333}} a{{color:#2563eb}}
</style></head><body>
<h1>📊 Question guide — helpful stats</h1>
<p class="sub">Calibrate your guesses. <a href="index.html">← back to live standings</a></p>
<div class="warn"><b>Read this first:</b> 2026 has <b>104 matches</b> (48 teams), vs <b>64</b> in every
past World Cup. Every tournament total — goals, own goals, red cards, shootouts — scales up by
roughly <b>1.6×</b>. Most people will anchor on old 64-game numbers. Don't.</div>
{blocks}
</body></html>"""
    (OUT / "guide.html").write_text(html)


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
<p class="sub">Auto-updated {updated} · {agg['matches_played']}/{agg['matches_total']} matches played · <a href="guide.html">📊 question guide &amp; stats</a></p>
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
    write_guide()
    print(f"\nWrote CSVs + index.html + guide.html to {OUT}/")


if __name__ == "__main__":
    main()
