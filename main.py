"""Clash Royale emulator: simulate battles, tune an AI, and climb the trophy road.

Examples:
    python main.py battle --deck giant_beatdown --opponent strategic --replay replay.html
    python main.py tune --generations 8 --out best_strategy.json
    python main.py ladder --strategy best_strategy.json --battles 400
    python main.py showcase --out battles.html
    python main.py watch          # play new games and open them in your browser
"""
import argparse
import os
import random

from crsim.agents import AGENTS, PlannerAgent, StrategicAgent
from crsim.cards import DECKS
from crsim.engine import Battle
from crsim.ladder import arena_for, opponent_for, run_ladder
from crsim.replay import export_games
from crsim import tune as tuning


def load_strategy(path):
    if path and os.path.exists(path):
        s = tuning.load(path)
        return s["deck"], s["params"]
    return None, None


AI_AGENTS = {"planner": PlannerAgent, "strategic": StrategicAgent}


def make_ai(a, params):
    return lambda: AI_AGENTS[a.agent](params)


def cmd_battle(a):
    deck, params = load_strategy(a.strategy)
    deck = a.deck or deck or "giant_beatdown"
    opp_deck = a.opponent_deck or random.Random(a.seed).choice(sorted(DECKS))
    opp_cls = AGENTS[a.opponent]
    opp = opp_cls(seed=a.seed) if a.opponent in ("random", "simple") else opp_cls()
    b = Battle([DECKS[deck], DECKS[opp_deck]], [make_ai(a, params)(), opp],
               levels=(a.level, a.opponent_level), seed=a.seed, record=bool(a.replay))
    r = b.run()
    outcome = {0: "WIN", 1: "LOSS", -1: "DRAW"}[r.winner]
    print(f"{deck} (you) vs {opp_deck} ({a.opponent}): {outcome} "
          f"{r.crowns[0]}-{r.crowns[1]} in {r.duration:.0f}s; "
          f"elixir spent {r.spent[0]:.0f}/{r.spent[1]:.0f}, leaked {r.leaked[0]:.1f}")
    if a.replay:
        export_games([(r.frames, game_meta(r, deck, a.level, opp_deck, a.opponent_level,
                                           a.opponent))], a.replay)
        print(f"replay written to {a.replay}")


def deck_name(cards):
    return next((k for k, v in DECKS.items() if v == cards), "custom")


def game_meta(r, deck, level, opp_deck, opp_level, opp_agent, trophies=None):
    return {"result": {0: "WIN", 1: "LOSS", -1: "DRAW"}[r.winner],
            "crowns": list(r.crowns), "duration": round(r.duration, 1),
            "my_deck": deck, "my_level": round(level, 1),
            "opp_deck": opp_deck, "opp_level": round(opp_level, 1),
            "opp_agent": opp_agent, "trophies": trophies}


def record_games(a, trophy_list, seed):
    deck, params = load_strategy(a.strategy)
    deck = a.deck or deck or "giant_beatdown"
    games = []
    for trophies in trophy_list:
        rng = random.Random(seed * 7919 + trophies)
        opp, opp_cards, opp_level = opponent_for(trophies, rng)
        r = Battle([DECKS[deck], opp_cards], [make_ai(a, params)(), opp],
                   levels=(a.level, opp_level), seed=rng.randrange(1 << 30), record=True).run()
        meta = game_meta(r, deck, a.level, deck_name(opp_cards), opp_level, opp.name, trophies)
        print(f"{trophies:5d} trophies ({arena_for(trophies)}): {meta['result']} "
              f"{r.crowns[0]}-{r.crowns[1]} vs {meta['opp_deck']} ({opp.name}, lv {opp_level:.1f})")
        games.append((r.frames, meta))
    return games


def cmd_showcase(a):
    """Record ladder games at several trophy counts and write a replay page."""
    export_games(record_games(a, a.trophies, a.seed), a.out, standalone=not a.fragment)
    print(f"replays written to {a.out}")


def cmd_watch(a):
    """Play fresh games and open them in the browser."""
    import time
    import webbrowser
    seed = a.seed if a.seed is not None else int(time.time())
    print(f"simulating {a.games} games (seed {seed}), about 1 s each...")
    trophies = [a.trophies + 100 * i for i in range(a.games)]
    export_games(record_games(a, trophies, seed), a.out)
    path = os.path.abspath(a.out)
    print(f"opening {path}")
    if not webbrowser.open("file://" + path):
        print("could not open a browser; open the file above manually")


def cmd_tune(a):
    best = tuning.tune(generations=a.generations, population=a.population,
                       games=a.games, level=a.level, seed=a.seed, workers=a.workers,
                       agent=a.agent, decks=a.decks,
                       start=tuning.load(a.start) if a.start and os.path.exists(a.start) else None)
    tuning.save(best, a.out)
    print(f"\nbest deck: {best['deck']} {best['cards']}")
    print(f"win rate {best['win_rate']:.1%}, {best['trophies_per_hour']:+.0f} trophies/hour")
    print(f"saved to {a.out}")


def cmd_ladder(a):
    deck, params = load_strategy(a.strategy)
    deck = a.deck or deck or "giant_beatdown"
    print(f"climbing with {deck} (level {a.level}), {a.agent} AI, "
          f"{'tuned' if params else 'default'} strategy")
    rep = run_ladder(make_ai(a, params), DECKS[deck], level=a.level,
                     battles=a.battles, seed=a.seed, plateau=a.plateau, log=print)
    print(rep.summary())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("battle", help="play a single battle")
    b.add_argument("--deck", choices=sorted(DECKS))
    b.add_argument("--opponent", default="strategic", choices=sorted(AGENTS))
    b.add_argument("--opponent-deck", choices=sorted(DECKS))
    b.add_argument("--opponent-level", type=float, default=11)
    b.add_argument("--replay", help="write an HTML replay to this path")

    t = sub.add_parser("tune", help="search for the most trophy-efficient deck + strategy")
    t.add_argument("--generations", type=int, default=8)
    t.add_argument("--population", type=int, default=16)
    t.add_argument("--games", type=int, default=48, help="games per candidate")
    t.add_argument("--workers", type=int)
    t.add_argument("--out", default="best_strategy.json")
    t.add_argument("--agent", default="planner", choices=sorted(AI_AGENTS))
    t.add_argument("--decks", nargs="+", choices=sorted(DECKS),
                   help="restrict the search to these decks")
    t.add_argument("--start", default="best_strategy.json",
                   help="seed the search with this saved strategy, if it exists")

    lad = sub.add_parser("ladder", help="climb the trophy road")
    lad.add_argument("--deck", choices=sorted(DECKS))
    lad.add_argument("--battles", type=int, default=400)
    lad.add_argument("--plateau", type=int, default=80,
                     help="stop after this many battles without a new peak (0 = never)")

    sh = sub.add_parser("showcase", help="record games across the ladder into one replay page")
    sh.add_argument("--deck", choices=sorted(DECKS))
    sh.add_argument("--trophies", type=int, nargs="+",
                    default=[1500, 4500, 6500, 7500, 8000, 9000])
    sh.add_argument("--out", default="battles.html")
    sh.add_argument("--fragment", action="store_true",
                    help="write only the page body (for hosts that add their own <html>)")

    w = sub.add_parser("watch", help="play new games and open them in your browser")
    w.add_argument("--games", type=int, default=5)
    w.add_argument("--trophies", type=int, default=8500, help="trophies of the first game")
    w.add_argument("--out", default="watch.html")
    w.add_argument("--deck", choices=sorted(DECKS))

    for p in (b, t, lad, sh, w):
        p.add_argument("--level", type=float, default=11, help="your card level")
        p.add_argument("--seed", type=int, default=None if p is w else 0)
    for p in (b, lad, sh, w):
        p.add_argument("--agent", default="planner", choices=sorted(AI_AGENTS),
                       help="planner = look-ahead search (default); strategic = heuristic only")
        p.add_argument("--strategy", default="best_strategy.json",
                       help="tuned strategy JSON (from `tune`)")

    a = ap.parse_args()
    {"battle": cmd_battle, "tune": cmd_tune, "ladder": cmd_ladder,
     "showcase": cmd_showcase, "watch": cmd_watch}[a.cmd](a)


if __name__ == "__main__":
    main()
