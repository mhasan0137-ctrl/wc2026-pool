#!/usr/bin/env python3
"""
Points-tote leaderboard for the WC 2026 pool.

Reads two files in the repo root (NOT in out/, so they're committed):
  predictions.csv -- one row per person: name,q1_*,...,q13_*  (the template columns)
  results.csv     -- ONE row, the actual answer to each question (same q columns).
                     Fill it in as the tournament settles; blanks are skipped.

Writes out/standings.csv (name,points, sorted) and prints the table.
Also importable: compute_standings(pred_rows, result) -> [(name, points, detail)].

Scoring — each question is a 100-point pot:
  num/age   : the entry(ies) closest to the actual value split the 100.
  pick/band : entries exactly matching the actual answer split the 100.
  scoreline : Q9 — the 100 splits across the winning scorelines that were picked,
              then each scoreline's share splits among the people who picked it.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"

# (column, kind). kind: num | age | pick | scoreline | band
# band = ordered ranges scored by CLOSEST band (split ties), not exact match.
QUESTIONS = [
    ("q1_longest_name_letters", "num"),
    ("q2_own_goals", "num"),
    ("q3_red_cards", "num"),
    ("q4_pen_shootouts", "num"),
    ("q5_final_goals", "num"),
    ("q6_continent", "pick"),
    ("q7_group_fewest_goals", "pick"),
    ("q8_youngest_age", "age"),
    ("q9_scoreline_once", "scoreline"),
    ("q10_fastest_goal_band", "band"),
    ("q11_total_goals_band", "band"),
    ("q12_best_match_pnl_band", "band"),
    ("q13_most_traded_band", "band"),
]
# Ordered band options (must match the form), for closest-band scoring.
BANDS = {
    "q10_fastest_goal_band": ["0-10s", "11-20s", "21-30s", "31-40s", "41-50s", "51-60s",
                              "61-70s", "71-80s", "81-90s", "91s+"],
    "q11_total_goals_band": ["<220", "220-240", "241-260", "261-270", "271-280", "281-290",
                             "291-300", "301-310", "311-330", "331-350", ">350"],
    "q12_best_match_pnl_band": ["<£25k", "£25-50k", "£50-75k", "£75-100k", "£100-150k",
                                "£150-200k", "£200k+"],
    "q13_most_traded_band": ["<£1m", "£1-2m", "£2-3m", "£3-4m", "£4-6m", "£6-8m", "£8-10m",
                             "£10-15m", "£15m+"],
}
DEFAULT_POT = 100
# Per-question point pots (default 100 unless listed here).
POINTS = {
    "q2_own_goals": 50,
    "q3_red_cards": 50,
    "q4_pen_shootouts": 50,
    "q5_final_goals": 50,
    "q8_youngest_age": 25,
}


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def _age_days(s):
    """'18y 90d' -> days."""
    s = str(s).lower()
    import re
    m = re.match(r"\s*(\d+)\s*y\s*(\d+)\s*d", s)
    return int(m.group(1)) * 365 + int(m.group(2)) if m else None


def _norm(s):
    return str(s).strip().lower().replace(" ", "").replace("£", "").replace(",", "")


def _scoreline_key(s):
    """Unordered scoreline: '4-3' and '3-4' -> '3-4'."""
    nums = [n for n in str(s).replace("–", "-").split("-") if n.strip().isdigit()]
    return "-".join(sorted(nums, key=int)) if len(nums) == 2 else None


def compute_standings(pred_rows, result):
    points = defaultdict(float)
    detail = defaultdict(dict)
    for r in pred_rows:                 # everyone appears, even on 0
        points[r["name"]] += 0.0
    for col, kind in QUESTIONS:
        pot = POINTS.get(col, DEFAULT_POT)
        actual = (result or {}).get(col, "")
        if actual in (None, "", "?"):
            continue  # not settled yet
        picks = [(r["name"], r.get(col, "")) for r in pred_rows if r.get(col, "") not in ("", None)]

        if kind in ("num", "age"):
            conv = _num if kind == "num" else _age_days
            target = conv(actual)
            scored = [(n, conv(v)) for n, v in picks]
            scored = [(n, v) for n, v in scored if v is not None and target is not None]
            if not scored:
                continue
            best = min(abs(v - target) for _, v in scored)
            winners = [n for n, v in scored if abs(v - target) == best]
            share = pot / len(winners)
            for n in winners:
                points[n] += share
                detail[n][col] = round(share, 1)

        elif kind == "pick":
            # Q7 cascade: the winner is whoever picked the group with the FEWEST goals
            # AMONG THE GROUPS ACTUALLY PREDICTED. If someone picked the true fewest group
            # they win as normal; if nobody did, it cascades to the next-fewest group that
            # someone picked (and so on). Ties at that goal count share.
            gg = (result or {}).get("_q7_group_goals") if col == "q7_group_fewest_goals" else None
            if gg:
                ng = {_norm(g): v for g, v in gg.items()}
                scored = [(n, ng.get(_norm(v))) for n, v in picks]
                scored = [(n, v) for n, v in scored if v is not None]
                if scored:
                    lo = min(v for _, v in scored)
                    winners = [n for n, v in scored if v == lo]
                    share = pot / len(winners)
                    for n in winners:
                        points[n] += share
                        detail[n][col] = round(share, 1)
                continue
            # actual may be a single value, or several tied values "A;B;C" (e.g. a
            # group-fewest tie) - anyone who picked any of them shares the pot.
            accept = {_norm(x) for x in str(actual).split(";") if x.strip()}
            winners = [n for n, v in picks if _norm(v) in accept]
            if winners:
                share = pot / len(winners)
                for n in winners:
                    points[n] += share
                    detail[n][col] = round(share, 1)

        elif kind == "scoreline":
            # actual = once-only scorelines, e.g. "3-2;4-1". Winning picks = picks in that set.
            once = {_scoreline_key(x) for x in str(actual).replace(",", ";").split(";")}
            once.discard(None)
            pickers = defaultdict(list)
            for n, v in picks:
                k = _scoreline_key(v)
                if k in once:
                    pickers[k].append(n)
            if pickers:
                share = pot / len(pickers)            # split across winning scorelines
                for k, names in pickers.items():
                    per = share / len(names)          # then within each scoreline
                    for n in names:
                        points[n] += per
                        detail[n][col] = round(per, 1)

        elif kind == "band":
            # Ordered ranges: score the CLOSEST band(s) to the actual, splitting ties.
            order = [_norm(b) for b in BANDS.get(col, [])]
            tgt = _norm(actual)
            if not order or tgt not in order:
                continue
            # Q10 waterfall by EXACT SECONDS distance to each band's range when the seconds
            # are known (so a 64s goal is nearer 51-60s than 71-80s, not an even band-index tie).
            secs = (result or {}).get("_q10_seconds") if col == "q10_fastest_goal_band" else None
            if secs is not None:
                def _rng(lab):
                    s = lab.lower().replace("s", "").replace(" ", "")
                    if "+" in s:
                        return (float(s.replace("+", "")), float("inf"))
                    if "-" in s:
                        a, b = s.split("-", 1)
                        return (float(a), float(b))
                    return None
                rng = {}
                for b in BANDS.get(col, []):
                    try:
                        rng[_norm(b)] = _rng(b)
                    except ValueError:
                        rng[_norm(b)] = None
                def _sdist(v):
                    r = rng.get(_norm(v))
                    if not r:
                        return None
                    lo, hi = r
                    return 0.0 if lo <= secs <= hi else (secs - hi if secs > hi else lo - secs)
                scored = [(n, _sdist(v)) for n, v in picks]
                scored = [(n, d) for n, d in scored if d is not None]
            else:
                ti = order.index(tgt)
                scored = [(n, abs(order.index(_norm(v)) - ti)) for n, v in picks if _norm(v) in order]
            if not scored:
                continue
            best = min(d for _, d in scored)
            winners = [n for n, d in scored if d == best]
            share = pot / len(winners)
            for n in winners:
                points[n] += share
                detail[n][col] = round(share, 1)

    table = sorted(((n, round(p, 1), detail[n]) for n, p in points.items()),
                   key=lambda x: -x[1])
    return table


def _load(path):
    if not path.exists():
        return None
    with open(path) as f:
        return list(csv.DictReader(f))


def main():
    preds = _load(HERE / "predictions.csv")
    results = _load(HERE / "results.csv")
    if not preds:
        sys.exit("No predictions.csv found (one row per person, the template columns).")
    preds = [r for r in preds if not r["name"].startswith("EXAMPLE_ROW")]
    result = results[0] if results else {}
    table = compute_standings(preds, result)

    OUT.mkdir(exist_ok=True)
    with open(OUT / "standings.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "points"])
        for i, (n, p, _) in enumerate(table, 1):
            w.writerow([i, n, p])

    print(f"Leaderboard ({len(preds)} entries, {sum(1 for c,_ in QUESTIONS if (result or {}).get(c) not in ('', None, '?'))} questions settled):")
    for i, (n, p, _) in enumerate(table, 1):
        print(f"  {i:>2}. {n:<20} {p:>6.1f}")
    print(f"\nWrote {OUT/'standings.csv'}")


if __name__ == "__main__":
    main()
