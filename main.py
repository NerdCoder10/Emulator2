"""Clash Royale emulator: simulate battles, tune an AI, and climb the trophy road.

Examples:
    python main.py battle --deck giant_beatdown --opponent strategic --replay replay.html
    python main.py tune --generations 8 --out best_strategy.json
    python main.py ladder --strategy best_strategy.json --battles 400
"""
import argparse
import os
import random

from crsim.agents import AGENTS, StrategicAgent
from crsim.cards import DECKS
from crsim.engine import Battle
from crsim.ladder import run_ladder
from crsim.replay import export_html
from crsim import tune as tuning


def load_strategy(path):
    if path and os.path.exists(path):
        s = tuning.load(path)
        return s["deck"], s["params"]
    return None, None


def cmd_battle(a):
    deck, params = load_strategy(a.strategy)
    deck = a.deck or deck or "giant_beatdown"
    opp_deck = a.opponent_deck or random.Random(a.seed).choice(sorted(DECKS))
    opp_cls = AGENTS[a.opponent]
    opp = opp_cls(seed=a.seed) if a.opponent in ("random", "simple") else opp_cls()
    b = Battle([DECKS[deck], DECKS[opp_deck]], [StrategicAgent(params), opp],
               levels=(a.level, a.opponent_level), seed=a.seed, record=bool(a.replay))
    r = b.run()
    outcome = {0: "WIN", 1: "LOSS", -1: "DRAW"}[r.winner]
    print(f"{deck} (you) vs {opp_deck} ({a.opponent}): {outcome} "
          f"{r.crowns[0]}-{r.crowns[1]} in {r.duration:.0f}s; "
          f"elixir spent {r.spent[0]:.0f}/{r.spent[1]:.0f}, leaked {r.leaked[0]:.1f}")
    if a.replay:
        export_html(r.frames, a.replay, f"{deck} vs {opp_deck}: {outcome}")
        print(f"replay written to {a.replay}")


def cmd_tune(a):
    best = tuning.tune(generations=a.generations, population=a.population,
                       games=a.games, level=a.level, seed=a.seed, workers=a.workers)
    tuning.save(best, a.out)
    print(f"\nbest deck: {best['deck']} {best['cards']}")
    print(f"win rate {best['win_rate']:.1%}, {best['trophies_per_hour']:+.0f} trophies/hour")
    print(f"saved to {a.out}")


def cmd_ladder(a):
    deck, params = load_strategy(a.strategy)
    deck = a.deck or deck or "giant_beatdown"
    print(f"climbing with {deck} (level {a.level}) "
          f"{'tuned' if params else 'default'} strategy")
    rep = run_ladder(lambda: StrategicAgent(params), DECKS[deck], level=a.level,
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

    lad = sub.add_parser("ladder", help="climb the trophy road")
    lad.add_argument("--deck", choices=sorted(DECKS))
    lad.add_argument("--battles", type=int, default=400)
    lad.add_argument("--plateau", type=int, default=80,
                     help="stop after this many battles without a new peak (0 = never)")

    for p in (b, t, lad):
        p.add_argument("--level", type=float, default=11, help="your card level")
        p.add_argument("--seed", type=int, default=0)
    for p in (b, lad):
        p.add_argument("--strategy", default="best_strategy.json",
                       help="tuned strategy JSON (from `tune`)")

    a = ap.parse_args()
    {"battle": cmd_battle, "tune": cmd_tune, "ladder": cmd_ladder}[a.cmd](a)


if __name__ == "__main__":
    main()
