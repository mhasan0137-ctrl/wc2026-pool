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
import random
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
WC_LEAGUE_ID = 1      # FIFA World Cup in API-Football
WC_SEASON = 2026

OUT = Path(__file__).parent / "out"

# Entries stay hidden until 48 hours after the tournament starts, so nobody can
# copy and the early predictions can't be reverse-engineered from the first results.
# First kickoff: 11 June 2026, 18:00 BST = 17:00 UTC. Reveal: 48h later.
KICKOFF = datetime(2026, 6, 11, 17, 0, tzinfo=timezone.utc)
REVEAL = KICKOFF + timedelta(hours=48)   # 13 June 2026, 17:00 UTC


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
    group_goals = defaultdict(int)
    scorers = defaultdict(int)
    pen_shootouts = []
    own_goals = 0
    scoreline_counts = Counter()

    for m in played:
        a, b = m["score"]["ft"]
        g = a + b
        total_goals += g
        scoreline_counts["-".join(map(str, sorted((a, b))))] += 1
        for gk in ("goals1", "goals2", "goals"):
            for gg in m.get(gk) or []:
                if isinstance(gg, dict) and gg.get("owngoal"):
                    own_goals += 1
        team_for[m["team1"]] += a
        team_for[m["team2"]] += b
        team_against[m["team1"]] += b
        team_against[m["team2"]] += a
        if m.get("group"):
            group_goals[m["group"]] += g
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
        "group_played": sum(1 for m in played if m.get("group")),
        "group_total": sum(1 for m in matches if m.get("group")),
        "all_groups": sorted({m["group"] for m in matches if m.get("group")}),
        "total_goals": total_goals,
        "avg_goals_per_match": round(total_goals / len(played), 2) if played else 0,
        "highest_scoring": high,
        "five_plus_games": five_plus,
        "penalty_shootouts": pen_shootouts,
        "team_for": dict(team_for),
        "team_against": dict(team_against),
        "group_goals": dict(group_goals),
        "scorers": scorers,
        "own_goals": own_goals,
        "scoreline_counts": dict(scoreline_counts),
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


# ----- Static reference data for the guide page (all verified historical figures) -----
# Per-tournament totals. GOALS AND FINAL-GOALS EXCLUDE PENALTY-SHOOTOUT KICKS.
# cols: label, matches, goals, own goals, red cards, penalty shootouts, final (goals in play)
TOURNAMENT_STATS = [
    ("WC 2014 (Brazil)", 64, 171, 5, 10, 4, "Germany 1-0 Argentina (a.e.t.) - <b>1</b>"),
    ("WC 2018 (Russia)", 64, 169, 12, 4, 4, "France 4-2 Croatia - <b>6</b>"),
    ("WC 2022 (Qatar)", 64, 172, 2, 4, 5, "Argentina 3-3 France, 4-2 pens - <b>12</b>"),
    ("Euro 2020", 51, 142, 11, 1, 4, "Italy 1-1 England, 3-2 pens - <b>7</b>"),
    ("Euro 2024", 51, 117, 10, 6, 3, "Spain 2-1 England - <b>3</b>"),
    ("WC 2026 ← you're predicting", 104, "?", "?", "?", "?", "? (the final)"),
]

# 2026 teams by confederation (the "winning continent" question). Counts = 48 total.
CONFEDERATIONS = [
    ("UEFA - Europe", 16,
     "England, France, Germany, Spain, Portugal, Netherlands, Belgium, Croatia, "
     "Switzerland, Austria, Norway, Scotland, Sweden, Turkey, Bosnia & Herzegovina, Czech Republic"),
    ("CONMEBOL - South America", 6,
     "Argentina, Brazil, Uruguay, Colombia, Ecuador, Paraguay"),
    ("CAF - Africa", 10,
     "Morocco, Senegal, Egypt, Algeria, Tunisia, Ivory Coast, Ghana, South Africa, Cape Verde, DR Congo"),
    ("AFC - Asia", 9,
     "Japan, South Korea, Iran, Australia, Saudi Arabia, Qatar, Uzbekistan, Jordan, Iraq"),
    ("CONCACAF - N./C. America", 6,
     "USA, Mexico, Canada, Panama, Haiti, Curaçao"),
    ("OFC - Oceania", 1, "New Zealand"),
]

# Rough win chance by continent, from market outright odds (June 2026), normalised to 100%.
CONTINENT_CHANCES = [
    ("Europe (UEFA)", "~71%"),
    ("South America (CONMEBOL)", "~21%"),
    ("Africa (CAF)", "~3%"),
    ("N./C. America (CONCACAF)", "~3%"),
    ("Asia (AFC)", "~2%"),
    ("Oceania (OFC)", "<1%"),
]

# Youngest goalscorer in each of the last six tournaments (chronological order).
YOUNGEST_BY_TOURNAMENT = [
    ("WC 2014", "Julian Green", "USA", "19y 25d"),
    ("Euro 2016", "Renato Sanches", "Portugal", "18y 317d"),
    ("WC 2018", "Kylian Mbappé", "France", "19y 183d"),
    ("Euro 2020", "Mikkel Damsgaard", "Denmark", "20y 353d"),
    ("WC 2022", "Gavi", "Spain", "18y 110d"),
    ("Euro 2024", "Lamine Yamal", "Spain", "16y 362d"),
]

# Scorelines (unordered) that occurred EXACTLY ONCE - computed from openfootball.
SCORELINE_ONCE_HISTORY = [
    ("WC 2018", 9, "0-0, 1-3, 0-5, 2-3, 3-3, 2-4, 2-5, 1-6, 3-4"),
    ("WC 2022", 5, "2-4, 3-3, 0-7, 1-6, 2-6"),
    ("Euro 2020", 3, "1-4, 0-5, 2-4"),
    ("Euro 2024", 4, "2-2, 2-3, 1-4, 1-5"),
]

# Fastest goal in each of the last five tournaments (chronological).
FASTEST_GOALS = [
    ("WC 2014", "Clint Dempsey", "USA", "30s", "21-30s"),
    ("WC 2018", "Mathias Jørgensen", "Denmark", "55s", "51-60s"),
    ("Euro 2020", "Emil Forsberg", "Sweden", "81s (1:21)", "81-90s"),
    ("WC 2022", "Alphonso Davies", "Canada", "67s", "61-70s"),
    ("Euro 2024", "Nedim Bajrami", "Albania", "23s", "21-30s"),
]

# Static helper notes, one per pool question.
QUESTION_GUIDE = [
    ("1. Number of letters in the longest goalscorer's name",
     "First name + surname; particles (De, van, Mac) count, plain middle names don't, "
     "hyphen double-barrels count - Trent Alexander-Arnold = 20. Only goalscorers count. "
     "Recent tournaments' longest-named scorers have run ~<b>20-22</b> letters (Castelletto 22), so ~<b>20</b> is a fair anchor."
     "</p><p><i>See the “Q1 - longest names in the 2026 squads” section below (plus the longest-named "
     "goalscorers from recent tournaments).</i>"),
    ("2. Own goals in the tournament (50 pts)",
     "Wildly swingy and impossible to call precisely. Based on recent tournaments, over 104 games the total "
     "might land somewhere between ~<b>3</b> and ~<b>22</b>. <i>(Excludes shootouts.)</i>"
     "</p><p><i>See the “Recent tournaments at a glance” and “Per game → what it means for 2026 (104 games)” tables below (own-goals row).</i>"),
    ("3. Red cards in the tournament (50 pts)",
     "VAR keeps modern World Cups low. Based on recent tournaments, over 104 games it might land somewhere "
     "between ~<b>2</b> and ~<b>16</b> (the recent norm is nearer ~6-7)."
     "</p><p><i>See the “Recent tournaments at a glance” and “Per game → what it means for 2026 (104 games)” tables below (red-cards row).</i>"),
    ("4. Penalty shootouts (50 pts)",
     "Recent tournaments had <b>3-5</b>. 2026 has <b>double the knockout games</b> (32 vs 16), so just double "
     "it: expect ~<b>6-10</b>."
     "</p><p><i>See the “Recent tournaments at a glance” and “Per game → what it means for 2026 (104 games)” tables below (penalty-shootouts row).</i>"),
    ("5. Goals in the final (50 pts)",
     "A coin-flip - and <b>shootout kicks count here</b>. If the final is settled in play it's typically "
     "<b>1-6</b> goals; if it goes to penalties, add the shootout kicks scored (often ~6-10 more) on top."
     "</p><p><i>See the “Recent tournaments at a glance” table below (Final column - it now includes the "
     "shootout kicks).</i>"),
    ("6. Winning continent",
     "Only <b>Europe (UEFA)</b> and <b>South America (CONMEBOL)</b> have <i>ever</i> won a World Cup. "
     "No African, Asian, CONCACAF or Oceanian team ever has - so 'Other' pays a fortune if it lands."
     "</p><p><i>See the “Q6 - the 48 teams by confederation” section below (teams + continent win chances).</i>"),
    ("7. Group with fewest total goals",
     "12 groups of 4 (six games each). Look for an <b>evenly balanced</b> group with no obvious whipping boys - "
     "tight, cagey games keep the total down (Groups A, B or D look like candidates). A tough one to call, "
     "so it's as much a punt as a read."),
    ("8. Youngest goalscorer (age) - 25 pts",
     "Give it as years + days. Based on recent tournaments the youngest scorer is usually around <b>18-19</b> "
     "(as low as ~16 at Euro '24). <b>Hint:</b> Lamine Yamal (Spain) will be <b>18</b> (turning 19 mid-tournament) "
     "and is near-certain to play and score - so ~<b>18y</b> is a strong anchor, unless a 17-year-old like "
     "Gilberto Mora (Mexico) nets first."
     "</p><p><i>See the “Q8 - youngest scorer in each of the last 6 tournaments” section below (and the youngest 2026 squad players).</i>"),
    ("9. Pick a scoreline that happens exactly once",
     "Common scorelines (1-0, 2-1, 1-1) recur many times; rarer ones (4-3, 5-2, 3-3) often happen 0 or 1 "
     "times. The sweet spot is a scoreline plausible enough to occur, rare enough to occur only once. "
     "Scorelines are <b>unordered</b> - <b>reversed scores are treated as the same</b>: it doesn't matter which "
     "team scored what, so a 4-3 and a 3-4 are one and the same result and count together."
     "</p><p><i>Scoring: a scoreline <b>wins</b> if it occurred <b>exactly once</b> in the tournament. "
     "Q9's 100-point pot splits <b>equally across the winning scorelines first</b>, then each scoreline's "
     "share splits among the people who picked it - so a unique pick banks a whole share. "
     "<b>Example:</b> 5-4 happens once and only you picked it; 3-3 happens once and two others picked it → "
     "two winning scorelines, <b>50 each</b> → you take the full <b>50</b> for 5-4, the two 3-3 pickers get "
     "<b>25</b> each. (One winning scoreline + one picker → the full 100.) Shootouts don't change a "
     "scoreline.</i></p><p><i>See the “Q9 - scorelines that landed exactly once, recent tournaments” section below.</i>"),
    ("10. Fastest goal of the tournament (band)",
     "Pick a 10-second band for the tournament's fastest goal: <b>0-10s · 11-20s · 21-30s · 31-40s · 41-50s · "
     "51-60s · 61-70s · 71-80s · 81-90s · 91s+</b>. The all-time WC record is Şükür's 10.8s (2002)."
     "</p><p><i>See the “Q10 - fastest goal in the last 5 tournaments” section below (and the band each falls in).</i>"),
    ("11. Total goals in the whole tournament (band)",
     "Goals/game has trended up and there are far more games now - <b>≈285</b> is the central call. Pick a band "
     "(symmetric around 285): <b>&lt;220 · 220-240 · 241-260 · 261-270 · 271-280 · 281-290 · 291-300 · "
     "301-310 · 311-330 · 331-350 · &gt;350</b>. The all-time record of 172 (a 64-game number) is a terrible "
     "anchor. <i>(Excludes shootout kicks.)</i>"
     "</p><p><i>See the “Recent tournaments at a glance” and “Per game → what it means for 2026 (104 games)” tables below (total-goals row).</i>"),
    ("12. Most we make on a single group-stage match (net P&amp;L, £)",
     "💷 <b>Insider question.</b> Our trading book's <b>best single-match net P&amp;L</b> across the group "
     "stage. Pick a band - <b>&lt;£25k · £25-50k · £50-75k · £75-100k · £100-150k · £150-200k · £200k+</b>. "
     "<b>Hint:</b> our best single match at the last Euros was ~<b>£40k</b>, and we made ~<b>£44k</b> on "
     "this UCL final. Settled from our own numbers after the groups; right-band pickers split the pot."),
    ("13. Most we trade on a single group-stage match (turnover, £)",
     "💷 <b>Insider question.</b> The single group game we <b>trade the most money on</b> (turnover). "
     "Pick a band: <b>&lt;£1m · £1-2m · £2-3m · £3-4m · £4-6m · £6-8m · £8-10m · "
     "£10-15m · £15m+</b>. "
     "<b>Hint:</b> our highest group-stage turnover at the last Euros was ~<b>£3.3m</b>, and this UCL "
     "final did ~<b>£3m</b> - and a World Cup pulls bigger volume. Settled from our own numbers after the groups."),
]

# Best-effort long-named players LIKELY in 2026 squads (hand-picked - NOT exhaustive;
# longest_names.py with the API key produces the definitive ranking and replaces this).
# cols: letters, player, position, team, "plays & scores?" likelihood
LONGEST_NAMES_ESTIMATE = [
    (20, "Giorgian de Arrascaeta", "AM", "Uruguay", "Likely starts; scores occasionally - Med"),
    (20, "Trent Alexander-Arnold", "RB", "England", "Likely squad; rarely scores - Low"),
    (18, "Aurélien Tchouaméni", "DM", "France", "Starter; scores rarely - Low/Med"),
    (17, "Christopher Nkunku", "FW", "France", "Squad uncertain; scores if he plays - Med"),
    (17, "Alexis Mac Allister", "CM", "Argentina", "Starter; scores sometimes - Med"),
    (16, "Cristiano Ronaldo", "FW", "Portugal", "Likely captain; scores often - High"),
    (16, "Federico Valverde", "CM", "Uruguay", "Starter; scores sometimes - Med"),
    (15, "Youssef En-Nesyri", "ST", "Morocco", "Starter striker; scores often - High"),
    (15, "Teun Koopmeiners", "CM", "Netherlands", "Squad; scores sometimes - Med"),
    (15, "Randal Kolo Muani", "ST", "France", "Squad; scores sometimes - Med"),
]

# Score chance /10 derived purely from position (a scorer-propensity proxy).
POS_SCORE = {"FW": 6, "MF": 4, "DF": 2, "GK": 0}
# Start chance /10 - rough subjective estimate per player (role in their national team).
START_CHANCE = {
    "Amirhossein Hosseinzadeh": 3, "Amirmohammad Razzaghinia": 2,
    "Alexander Bernhardsson": 3, "Hossein Kanaanizadegan": 7,
    "Adalberto Carrasquilla": 8, "Jean-Ricner Bellegarde": 8,
    "Crysencio Summerville": 3, "Matias Fernandez-Pardo": 2,
    "Giorgian de Arrascaeta": 8, "Jaloliddin Masharipov": 7,
}

# Notable LONG-named goalscorers from recent tournaments (verified goals).
# Computed from openfootball (WC '18/'22, full names) + verified Euro '24 names.
HISTORICAL_LONG_SCORERS = [
    (22, "Jean-Charles Castelletto", "Cameroon", "WC 2022 (vs Serbia)"),
    (21, "Sergej Milinković-Savić", "Serbia", "WC 2022"),
    (20, "Giorgian de Arrascaeta", "Uruguay", "WC 2022 (vs Ghana)"),
    (20, "Khvicha Kvaratskhelia", "Georgia", "Euro 2024 (vs Portugal)"),
    (20, "Christoph Baumgartner", "Austria", "Euro 2024"),
    (18, "Aurélien Tchouaméni", "France", "WC 2022 (vs England)"),
    (17, "Georges Mikautadze", "Georgia", "Euro 2024"),
]

def _longest_names_rows():
    """Read top 10 from out/longest_names.csv if longest_names.py has been run."""
    path = OUT / "longest_names.csv"
    if not path.exists():
        return None
    rows = []
    with open(path) as f:
        for r in list(csv.DictReader(f))[:10]:
            rows.append((r["letters"], r["player"], r.get("position", "?"), r["team"]))
    return rows


def _youngest_members_rows():
    """Top 10 youngest squad players from out/youngest_members.csv (if scraped)."""
    path = OUT / "youngest_members.csv"
    if not path.exists():
        return None
    with open(path) as f:
        return [(r["age"], r["player"], r.get("position", "?"), r["team"])
                for r in list(csv.DictReader(f))[:10]]


def write_guide():
    """Render guide.html - helpful stats + reference tables for every pool question."""
    def tbl(header, body_rows):
        head = "".join(f"<th>{h}</th>" for h in header)
        body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                         for r in body_rows)
        return f"<table><tr>{head}</tr>{body}</table>"

    def pg(v, m, dp):
        return f"{v / m:.{dp}f}" if isinstance(v, int) else "?"

    summary_rows = []
    for label, m, g, og, rc, sh, fin in TOURNAMENT_STATS:
        summary_rows.append((label, m, g, pg(g, m, 2), og, pg(og, m, 3),
                             rc, pg(rc, m, 3), sh, pg(sh, m, 3), fin))
    summary = tbl(["Tournament", "Matches", "Goals", "Goals/game", "Own goals", "OG/game",
                   "Red cards", "Reds/game", "Pen shootouts", "Shootouts/game",
                   "Final (incl. shootout kicks - Q5)"], summary_rows)
    # Historical per-game RANGES, computed from the tournaments above, scaled to 104 games.
    numeric = [(g, og, rc, sh, m) for (_, m, g, og, rc, sh, _) in TOURNAMENT_STATS if isinstance(g, int)]

    def rng(idx):
        rates = [row[idx] / row[4] for row in numeric]
        return min(rates), max(rates)

    g_lo, g_hi = rng(0)
    og_lo, og_hi = rng(1)
    rc_lo, rc_hi = rng(2)
    sh_counts = [s for (_, _, _, _, _, s, _) in TOURNAMENT_STATS if isinstance(s, int)]
    sh_lo, sh_hi = min(sh_counts), max(sh_counts)
    proj_rows = [
        ("Total goals", f"{g_lo:.2f} - {g_hi:.2f} / game (trending up at WCs)",
         f"~{round(g_lo * 104)} - {round(g_hi * 104)} - <b>≈285 expected</b>"),
        ("Own goals", f"{og_lo:.2f} - {og_hi:.2f} / game",
         f"~{round(og_lo * 104)} - {round(og_hi * 104)}"),
        ("Red cards", f"{rc_lo:.2f} - {rc_hi:.2f} / game (VAR-era WCs ~0.06)",
         f"~{round(rc_lo * 104)} - {round(rc_hi * 104)}"),
        ("Penalty shootouts", f"{sh_lo}-{sh_hi} per tournament (in 16 KO games)",
         f"~{sh_lo * 2}-{sh_hi * 2} - <b>double</b> (2026 has 32 KO games)"),
    ]
    projections = tbl(["Metric", "Historical range (per game)", "Range over 2026 (104 games)"], proj_rows)
    confeds = tbl(["Confederation", "Teams", "Who"],
                  [(c, n, who) for c, n, who in CONFEDERATIONS])
    youngest = tbl(["Tournament", "Youngest scorer", "Country", "Age"], YOUNGEST_BY_TOURNAMENT)
    ym = _youngest_members_rows()
    # Scoring chance for these very young, fringe squad members is low - by position.
    young_score = {"FW": 2, "MF": 1, "DF": 1, "GK": 0}
    if ym:
        ym_rows = [(age, p, pos, t, f"{young_score.get(pos, 1)}/10") for (age, p, pos, t) in ym]
        youngest_members = tbl(["Age (8 Jun '26)", "Player", "Pos", "Team", "Score /10"], ym_rows)
    else:
        youngest_members = "<p class='sub'><i>(youngest-squad table populates when the squad scrape runs)</i></p>"
    fastest = tbl(["Tournament", "Player", "Country", "Fastest goal", "Band"], FASTEST_GOALS)
    scoreline_once = tbl(["Tournament", "# once-only", "The scorelines (unordered)"], SCORELINE_ONCE_HISTORY)

    ln = _longest_names_rows()
    if ln:
        body = [(L, p, pos, t, POS_SCORE.get(pos, "?"), START_CHANCE.get(p, "?"))
                for (L, p, pos, t) in ln]
        longest_block = ("<p>Top 10 longest names in the 2026 squads (pool rule applied, scraped from the "
                         "official squad lists). <b>Score /10</b> = scoring chance from position "
                         "(FW 6 · MF 4 · DF 2 · GK 0); <b>Start /10</b> = rough estimate of starting "
                         "(subjective - don't take to the bank):</p>"
                         + tbl(["Letters", "Player", "Pos", "Team", "Score /10", "Start /10"], body))
    else:
        longest_block = (
            '<p><b>Best-effort estimate</b> - hand-picked, likely squad members, <b>not exhaustive</b>. '
            'Run <code>longest_names.py</code> with the API key for the definitive top-10 from live squad data:</p>'
            + tbl(["Letters", "Player", "Pos", "Team", "Plays &amp; scores?"], LONGEST_NAMES_ESTIMATE))
    historical_block = tbl(["Letters", "Player", "Country", "When"], HISTORICAL_LONG_SCORERS)

    continent = tbl(["Continent", "Rough win chance"], CONTINENT_CHANCES)

    # ★ = quick stats in the tables below · ★★ = its own dedicated section below.
    MARKERS = {1: "★★", 2: "★", 3: "★", 4: "★", 5: "★", 6: "★★",
               8: "★★", 9: "★★", 10: "★★", 11: "★"}
    INSIDER = {12, 13}

    def q_block(title, body):
        num = int(title.split(".")[0])
        mark = f' <span class="mark">{MARKERS[num]}</span>' if num in MARKERS else ""
        cls = "q insider" if num in INSIDER else "q"
        return f'<div class="{cls}"><h3>{title}{mark}</h3><p>{body}</p></div>'

    blocks = "\n".join(q_block(t, b) for t, b in QUESTION_GUIDE)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Pool - Question Guide</title>
<style>
 body{{font:15px/1.6 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} h2{{margin-top:2rem;font-size:1.2rem}} .sub{{color:#666;margin-top:0}}
 .warn{{background:#fff6e5;border:1px solid #ffd58a;border-radius:8px;padding:.8rem 1rem;margin:1rem 0}}
 .note{{background:#eef4ff;border:1px solid #bcd2ff;border-radius:8px;padding:.6rem 1rem;margin:1rem 0;font-size:.92rem}}
 .q{{border-bottom:1px solid #e3e6ea;padding:.7rem 0}} .q h3{{margin:.2rem 0;font-size:1.05rem}}
 .q p{{margin:.3rem 0;color:#333}} a{{color:#2563eb}}
 .q.insider{{background:#fdf2f8;border:1px solid #f3c6e2;border-left:4px solid #c026d3;border-radius:8px;padding:.6rem .9rem;margin:.5rem 0}}
 .q.insider h3{{color:#a21caf}}
 table{{border-collapse:collapse;width:100%;margin:.6rem 0 1rem;font-size:.92rem}}
 th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e3e6ea;vertical-align:top}}
 th{{background:#fafbfc}} code{{background:#f2f4f7;padding:.05rem .3rem;border-radius:4px}}
 .mark{{color:#c026d3;font-size:.8rem;vertical-align:super}}
 .legend{{color:#666;font-size:.88rem}} hr{{border:0;border-top:2px solid #e3e6ea;margin:2.5rem 0 0}}
</style></head><body>
<h1>📊 Question guide - helpful stats</h1>
<p class="sub">Calibrate your guesses. <a href="index.html">← back to live standings</a></p>

<div class="warn"><b>Read this first:</b> 2026 has <b>104 matches</b> (48 teams), vs <b>64</b> in every
past World Cup (and 51 at a Euro). Every tournament total scales up by roughly <b>1.6x</b> vs an old
World Cup.</div>

<div class="note">📌 <b>Goal counts exclude penalty-shootout kicks - with one exception, Q5.</b> A shootout
decides who advances, but those kicks aren't goals, so <b>total goals (Q11)</b> counts only goals in play
(including extra time). <b>Q5 (goals in the final) is the exception</b> - it <b>does</b> add the shootout
kicks when the final goes to penalties.</div>

<p class="legend">Markers: <span class="mark">★</span> = stats in the reference tables below ·
<span class="mark">★★</span> = its own detailed section below. Each question is worth <b>100 points</b>
unless its heading says otherwise (e.g. 50 or 25 pts).</p>

{blocks}

<hr>
<h1 style="margin-top:1.5rem">📚 Reference &amp; stats</h1>

<h2>Recent tournaments at a glance <span class="mark">★</span></h2>
{summary}
<p class="sub">* final won on penalties - the Final column ADDS those shootout kicks (Q5 counts them); the Goals column does not.</p>

<h2>Per game → what it means for 2026 (104 games) <span class="mark">★</span></h2>
<p class="sub">The whole trick: take the recent <i>per-game</i> rate and stretch it over 104 games.</p>
{projections}
<p class="sub">📈 Goals/game has generally crept up at World Cups (2.27 in 1990 → ~2.65-2.69 lately), so
<b>~285 total goals</b> is a sensible central call for 104 games - and the all-time record of 172 (set in a
64-game tournament) is nowhere near the right anchor.</p>
<p class="sub">⚠️ Shootouts only happen in the knockouts. 2026 has <b>32 knockout games - double the old 16</b>, so just
double the recent count: <b>3-5 → ~6-10</b>.</p>

<h2>Q1 - longest names in the 2026 squads <span class="mark">★★</span></h2>
{longest_block}
<p class="sub" style="margin-top:1rem"><b>Long-named goalscorers from recent tournaments</b> (verified goals - your ceiling is a name like these that actually scores):</p>
{historical_block}

<h2>Q6 - the 48 teams by confederation <span class="mark">★★</span></h2>
{confeds}
<p class="sub">Win chance by continent, from the market's outright odds (normalised to 100%):</p>
{continent}
<p class="sub">Only UEFA &amp; CONMEBOL have ever won - so any non-European, non-South-American pick is a
genuine longshot that pays big on the tote. (A "winning <i>time-zone</i>" version is messier - the three
hosts alone span four US zones - so continent is the clean cut.)</p>

<h2>Q8 - youngest scorer in each of the last 6 tournaments <span class="mark">★★</span></h2>
{youngest}
<p class="sub">Youngest of the lot: Lamine Yamal <b>16y 362d</b> (Euro 2024) - youngest in Euros history.
The guessing sweet spot is ~<b>18-19</b>.</p>
<p class="sub" style="margin-top:1rem"><b>Youngest players in the 2026 squads</b> (age as of 8 June 2026).
Score /10 is low - they're young and mostly fringe, so unlikely to play big minutes or score:</p>
{youngest_members}

<h2>Q9 - scorelines that landed exactly once, recent tournaments <span class="mark">★★</span></h2>
{scoreline_once}
<p class="sub">Winners are nearly always <b>mid-rare</b> scorelines (3-3, 2-3, 2-4, 1-4); common results
(1-0, 2-1, 1-1) recur far too often to land just once. With <b>104 games</b> in 2026 (vs 64), expect a few
more once-only scorelines - and some very rare ones may now repeat.</p>

<h2>Q10 - fastest goal in the last 5 tournaments <span class="mark">★★</span></h2>
{fastest}
<p class="sub">Recent fastest goals land all over (21-30s up to 81-90s) - no clear favourite band. Bajrami's
23s (Euro '24) was the fastest Euros goal ever; the all-time WC record is Şükür's 10.8s (2002).</p>

</body></html>"""
    (OUT / "guide.html").write_text(html)


QLABELS = {
    "q1_longest_name_letters": "Q1. Longest goalscorer's name (letters)", "q2_own_goals": "Q2. Own goals",
    "q3_red_cards": "Q3. Red cards", "q4_pen_shootouts": "Q4. Penalty shootouts",
    "q5_final_goals": "Q5. Goals in the final", "q6_continent": "Q6. Winning continent",
    "q7_group_fewest_goals": "Q7. Group with fewest goals", "q8_youngest_age": "Q8. Youngest scorer age",
    "q9_scoreline_once": "Q9. Scoreline that happens once", "q10_fastest_goal_band": "Q10. Fastest goal",
    "q11_total_goals_band": "Q11. Total goals", "q12_best_match_pnl_band": "Q12. Highest PnL Match (Net PnL)",
    "q13_most_traded_band": "Q13. Most traded (turnover)",
}
DEMO_NAMES = ["Player A", "Player B", "Player C", "Player D", "Player E", "Player F",
              "Player G", "Player H", "Player I", "Player J", "Player K", "Player L"]
DEMO_OPTIONS = {
    "q1_longest_name_letters": [str(x) for x in range(18, 25)],
    "q2_own_goals": [str(x) for x in range(4, 20)],
    "q3_red_cards": [str(x) for x in range(2, 16)],
    "q4_pen_shootouts": [str(x) for x in range(5, 12)],
    "q5_final_goals": [str(x) for x in range(1, 8)],
    "q6_continent": ["Europe", "Europe", "Europe", "South America", "South America", "Africa", "Asia"],
    "q7_group_fewest_goals": ["Group " + c for c in "ABCDEFGHIJKL"],
    "q8_youngest_age": ["17y 300d", "18y 50d", "18y 150d", "18y 250d", "19y 10d"],
    "q9_scoreline_once": ["3-2", "4-1", "5-3", "4-2", "3-3", "2-0", "5-2"],
    "q10_fastest_goal_band": ["11-20s", "21-30s", "31-40s", "41-50s", "51-60s", "61-70s"],
    "q11_total_goals_band": ["261-270", "271-280", "281-290", "291-300", "301-310"],
    "q12_best_match_pnl_band": ["<25k", "25-50k", "50-75k", "75-100k", "100-150k"],
    "q13_most_traded_band": ["<1m", "1-2m", "2-3m", "3-4m", "4-6m", "6-8m", "8-10m"],
}


def _total_goals_band(n):
    if n < 220:
        return "<220"
    for hi, label in [(240, "220-240"), (260, "241-260"), (270, "261-270"), (280, "271-280"),
                      (290, "281-290"), (300, "291-300"), (310, "301-310"), (330, "311-330"),
                      (350, "331-350")]:
        if n <= hi:
            return label
    return ">350"


def build_live_results(agg, live_feed):
    """
    Current LIVE snapshot for the leaderboard + outcomes table. Reflects what's known
    SO FAR (0 before kickoff), not projections. Anything not yet determinable is left
    absent (renders as '-').
      2 own goals / 3 red cards / 4 shootouts: running counts (0 now)
      1 longest scorer, 9 scorelines-once, 11 total-goals band: appear once games are played
      5 final goals, 6 continent, 8 youngest age, 10 fastest goal: from live_feed when known
      12 net P&L, 13 turnover: from live_feed, default £0k / £0m
    """
    from longest_names_wiki import name_letters
    lf = {k: v for k, v in (live_feed or {}).items() if v not in ("", None)}
    gp = agg["matches_played"]
    res = {
        "q2_own_goals": agg["own_goals"],
        "q3_red_cards": lf.get("q3_red_cards", 0),
        "q4_pen_shootouts": len(agg["penalty_shootouts"]),
        "q12_best_match_pnl_band": lf.get("q12_best_match_pnl_band", "£0k"),
        "q13_most_traded_band": lf.get("q13_most_traded_band", "£0m"),
    }
    if agg["scorers"]:                       # 1 longest-named scorer so far
        res["q1_longest_name_letters"] = max(name_letters(n)[0] for (n, _t) in agg["scorers"])
    if gp:                                   # 9 scorelines that have happened exactly once so far
        once = ";".join(k for k, v in agg["scoreline_counts"].items() if v == 1)
        if once:
            res["q9_scoreline_once"] = once
    if gp:                                   # 11 total goals so far -> band
        res["q11_total_goals_band"] = _total_goals_band(agg["total_goals"])
    for k in ("q5_final_goals", "q6_continent", "q8_youngest_age", "q10_fastest_goal_band"):
        if lf.get(k):                        # held until the final / manual feed
            res[k] = lf[k]
    return res


def make_demo_predictions():
    """Stable (seeded) random demo entries, so the leaderboard previews with content."""
    rng = random.Random(2026)
    rows = []
    for name in DEMO_NAMES:
        row = {"name": name}
        for col, opts in DEMO_OPTIONS.items():
            row[col] = rng.choice(opts)
        rows.append(row)
    return rows


def write_html(agg, players, standings=None, is_demo=False, outcomes=None, show_entries=False):
    """Render a single self-contained index.html for GitHub Pages."""
    outcomes = outcomes or {}
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    standings = standings or []
    entries_nav = ' · <a href="entries.html">📝 everyone\'s entries</a>' if show_entries else ''

    lb_rows = "\n".join(
        f'<tr><td>{i}</td><td>{n}</td><td>{p:g}</td></tr>'
        for i, (n, p, _) in enumerate(standings, 1)) or '<tr><td colspan="3">-</td></tr>'
    demo_note = ('<div class="note">👀 <b>Preview only.</b> These are <b>placeholder names</b> scored against '
                 '<b>projected</b> final outcomes (e.g. ~285 total goals) - to show how the leaderboard works. '
                 'Drop real entries into <code>predictions.csv</code> and fill <code>results.csv</code> as the '
                 'tournament settles, and this becomes the real thing.</div>') if is_demo else ""
    def outcome_cell(k):
        if k == "q7_group_fewest_goals":          # show every group + its goals so far
            gg = agg["group_goals"]
            items = sorted(((g, gg.get(g, 0)) for g in agg["all_groups"]), key=lambda x: x[1])
            return " · ".join(f"{g.replace('Group ', '')}:{v}" for g, v in items) or "-"
        v = outcomes.get(k)
        return v if v not in (None, "") else "-"

    proj_rows = "\n".join(f"<tr><td>{QLABELS[k]}</td><td>{outcome_cell(k)}</td></tr>" for k in QLABELS)

    # Live counts: total so far, avg/game, forecast over 104 games (if the pace holds).
    gp = agg["matches_played"]

    def live_count_row(label, total):
        if gp:
            avg = total / gp
            return (label, total, f"{avg:.2f}", round(avg * 104))
        return (label, total, "-", "-")

    live_counts = [
        live_count_row("Own goals (Q2)", agg["own_goals"]),
        live_count_row("Red cards (Q3)", int(outcomes.get("q3_red_cards") or 0)),
        live_count_row("Penalty shootouts (Q4)", len(agg["penalty_shootouts"])),
        live_count_row("Total goals (Q11)", agg["total_goals"]),
    ]
    lc_rows = "\n".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>"
                        for a, b, c, d in live_counts)
    outcomes_heading = "Results so far (live - drives the leaderboard)"
    outcomes_sub = ("Everything the leaderboard scores on. Counts are live; '-' = not determinable yet "
                    "(needs the final, a scorer, or a manual input). Group goals shows every group, fewest first.")

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Office Pool</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} h2{{margin-top:2rem;font-size:1.2rem}} .sub{{color:#666;margin-top:0}}
 .note{{background:#fff6e5;border:1px solid #ffd58a;border-radius:8px;padding:.7rem 1rem;margin:1rem 0;font-size:.92rem}}
 .cards{{display:flex;flex-wrap:wrap;gap:1rem;margin:1.5rem 0}}
 .card{{flex:1 1 160px;background:#f4f6f8;border-radius:10px;padding:1rem}}
 .card .n{{font-size:1.8rem;font-weight:700}} .card .l{{color:#666;font-size:.85rem}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0 2rem}}
 th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e3e6ea}}
 th{{background:#fafbfc}} td:not(:first-child),th:not(:first-child){{text-align:right}}
 a{{color:#2563eb}} code{{background:#f2f4f7;padding:.05rem .3rem;border-radius:4px}}
</style></head><body>
<h1>⚽ WC 2026 Office Pool</h1>
<p class="sub">Auto-updated {updated} · <a href="guide.html">📊 question guide &amp; stats</a></p>
<div class="cards">
 <div class="card"><div class="n">{agg['matches_played']}/{agg['matches_total']}</div><div class="l">Matches played</div></div>
 <div class="card"><div class="n">{agg['group_played']}/{agg['group_total']}</div><div class="l">Group-stage games</div></div>
 <div class="card"><div class="n">{agg['matches_played'] - agg['group_played']}/{agg['matches_total'] - agg['group_total']}</div><div class="l">Knockout games</div></div>
</div>

<h2>🏆 Leaderboard {'(preview)' if is_demo else ''}</h2>
{demo_note}
<table><tr><th>#</th><th>Name</th><th>Points</th></tr>
{lb_rows}
</table>

<h2>{outcomes_heading}</h2>
<p class="sub">{outcomes_sub}</p>
<table><tr><th>Question</th><th>Result</th></tr>
{proj_rows}
</table>

<h2>Live counts (so far - forecast)</h2>
<p class="sub">Total so far, average per game, and the forecast if that pace holds over all 104 games.
(Shootouts only happen in knockouts, so their forecast is a rough floor - see the guide.)</p>
<table><tr><th>Metric</th><th>Total so far</th><th>Avg/game</th><th>Forecast (104 games)</th></tr>
{lc_rows}
</table>

<p><a href="shares.html">🔢 point shares per question</a>{entries_nav} · <a href="guide.html">📊 guide &amp; stats</a></p>
<p class="sub">Every number on this page comes from the {len(QLABELS)} pool questions only.
<a href="fixtures.csv">fixtures.csv</a> · <a href="standings.csv">standings.csv</a></p>
</body></html>"""
    (OUT / "index.html").write_text(html)


def write_entries(preds, show):
    """Public 'who picked what' page. Until kickoff it shows a locked placeholder so
    nobody can copy; afterwards it renders every entry as submitted (name x question)."""
    if show and preds:
        cols = list(QLABELS.keys())
        head = "<tr><th>Name</th>" + "".join(f"<th>{QLABELS[c]}</th>" for c in cols) + "</tr>"
        body_rows = "".join(
            "<tr><td>" + (p.get("name") or "?") + "</td>"
            + "".join(f"<td>{p.get(c) or '-'}</td>" for c in cols) + "</tr>"
            for p in sorted(preds, key=lambda r: (r.get("name") or "").lower()))
        inner = ('<p class="sub">Every entry, as submitted - find your row.</p>'
                 f'<div class="scroll"><table>{head}{body_rows}</table></div>')
    else:
        inner = ('<p class="sub">Locked. Everyone\'s answers appear here <b>48 hours after the '
                 'tournament kicks off</b> (from 13 June, 18:00 BST) - hidden until then so nobody '
                 'can copy.</p>')
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Pool - Entries</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} .sub{{color:#666;margin-top:.1rem}}
 .scroll{{overflow-x:auto}}
 table{{border-collapse:collapse;margin:.6rem 0;font-size:.9rem}}
 th,td{{text-align:left;padding:.35rem .55rem;border-bottom:1px solid #e3e6ea;white-space:nowrap}}
 th{{background:#fafbfc}} a{{color:#2563eb}}
</style></head><body>
<h1>📝 Everyone's entries</h1>
<p class="sub"><a href="index.html">← leaderboard</a></p>
{inner}
</body></html>"""
    (OUT / "entries.html").write_text(html)


def write_shares(standings, outcomes):
    """Per-question point-shares page: for each question, the pot, the result so far,
    and how its points are currently split across players."""
    import settle
    outcomes = outcomes or {}
    secs = []
    for col, _kind in settle.QUESTIONS:
        pot = settle.POINTS.get(col, settle.DEFAULT_POT)
        result = outcomes.get(col)
        result = result if result not in (None, "") else "not settled yet"
        shares = sorted(((n, d[col]) for (n, _t, d) in standings if col in d), key=lambda x: -x[1])
        body = "".join(f"<tr><td>{n}</td><td>{s:g}</td></tr>" for n, s in shares) \
            or '<tr><td colspan="2">nobody scoring this yet</td></tr>'
        secs.append(f'<h2>{QLABELS.get(col, col)} <span class="pot">{pot} pts</span></h2>'
                    f'<p class="sub">Result so far: <b>{result}</b></p>'
                    f'<table><tr><th>Player</th><th>Points</th></tr>{body}</table>')
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Pool - Point shares per question</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} h2{{margin-top:1.8rem;font-size:1.1rem}} .sub{{color:#666;margin-top:.1rem}}
 .pot{{background:#eef2ff;color:#4338ca;border-radius:6px;padding:.05rem .4rem;font-size:.8rem;vertical-align:middle}}
 table{{border-collapse:collapse;width:100%;margin:.4rem 0 1rem}}
 th,td{{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #e3e6ea}}
 th{{background:#fafbfc}} td:not(:first-child),th:not(:first-child){{text-align:right}} a{{color:#2563eb}}
</style></head><body>
<h1>🔢 Point shares per question</h1>
<p class="sub">How each question's pot is currently split, given the results so far.
<a href="index.html">← leaderboard</a></p>
{''.join(secs)}
</body></html>"""
    (OUT / "shares.html").write_text(html)


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

    # group_goals.csv -- goals per group, for Q7 (group with fewest goals)
    write_csv(
        OUT / "group_goals.csv",
        sorted(agg["group_goals"].items(), key=lambda kv: kv[1]),
        ["group", "goals"],
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
        print("\n--players requested but API_FOOTBALL_KEY not set - skipping "
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
              f"scorers list - not all players): {total_reds}")
        print("   -> wrote players_apifootball.csv")

    # Refresh longest-names + youngest-members from Wikipedia squads (keyless). Best-effort.
    try:
        from datetime import date
        from longest_names_wiki import scrape, longest
        squad = scrape()
        if squad:
            write_csv(OUT / "longest_names.csv", longest(squad),
                      ["letters", "player", "position", "team"])

            ref = date(2026, 6, 8)
            def age_yd(born):
                b = date(*born)
                had_bday = (ref.month, ref.day) >= (b.month, b.day)
                years = ref.year - b.year - (0 if had_bday else 1)
                last = date(ref.year if had_bday else ref.year - 1, b.month, b.day)
                return years, (ref - last).days

            aged = []
            for p in squad:
                if not p["born"]:
                    continue
                try:
                    y, d = age_yd(p["born"])
                except ValueError:           # e.g. Feb 29 birthday
                    continue
                aged.append((y * 366 + d, f"{y}y {d}d", p["name"], p["pos"], p["team"]))
            aged.sort()
            write_csv(OUT / "youngest_members.csv",
                      [(age, n, pos, t) for _, age, n, pos, t in aged],
                      ["age", "player", "position", "team"])
            print(f"Scraped {len(squad)} squad players (longest names + youngest members).")
    except Exception as e:
        print(f"(squad scrape skipped: {e})")

    # Leaderboard. Real predictions -> LIVE results (per-question rules) + manual live_feed.csv
    # + results.csv overrides. No predictions yet -> seeded demo scored vs projected outcomes.
    standings, is_demo, outcomes = [], False, {}
    show_entries = False
    try:
        import settle
        root = Path(__file__).parent

        def _one_row(name):
            p = root / name
            if p.exists():
                with open(p) as f:
                    return (list(csv.DictReader(f)) or [{}])[0]
            return {}

        # Current live snapshot drives BOTH the outcomes table and the leaderboard.
        outcomes = build_live_results(agg, _one_row("live_feed.csv"))
        outcomes.update({k: v for k, v in _one_row("results.csv").items() if v not in ("", None)})
        # Real entries live in a hidden, read-only file (.predictions.csv); fall
        # back to the plain name, else demo. The on-site entries page stays gated
        # until REVEAL regardless of this file being present.
        pred_path = root / ".predictions.csv"
        if not pred_path.exists():
            pred_path = root / "predictions.csv"
        if pred_path.exists():
            with open(pred_path) as f:
                preds = [r for r in csv.DictReader(f) if not r["name"].startswith("EXAMPLE_ROW")]
        else:
            preds, is_demo = make_demo_predictions(), True
        show_entries = (not is_demo) and (datetime.now(timezone.utc) >= REVEAL)
        write_entries(preds, show_entries)
        standings = settle.compute_standings(preds, outcomes)
        write_csv(OUT / "standings.csv",
                  [(i, n, p) for i, (n, p, _) in enumerate(standings, 1)], ["rank", "name", "points"])
        write_shares(standings, outcomes)
        print(f"Standings: {len(standings)} entries" + (" (demo names)" if is_demo else ""))
    except Exception as e:
        print(f"(standings skipped: {e})")

    write_html(agg, players, standings, is_demo, outcomes, show_entries)
    write_guide()
    entries_note = "entries.html (live)" if show_entries else "entries.html (locked until kickoff + 48h)"
    print(f"\nWrote CSVs + index.html + guide.html + shares.html + {entries_note} to {OUT}/")


if __name__ == "__main__":
    main()
