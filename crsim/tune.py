"""Evolutionary search for the most trophy-efficient deck + strategy."""
import json
import os
import random
from multiprocessing import Pool

from .agents import AGENTS, DEFAULT_PARAMS
from .cards import DECKS
from .engine import Battle
from .ladder import LOSS_TROPHIES, MATCH_OVERHEAD, WIN_TROPHIES, opponent_for

PARAM_RANGES = {
    "attack_elixir": (5.0, 10.0),
    "punish_elixir": (0.0, 6.0),
    "spell_ratio": (0.6, 2.5),
    "tower_tolerance": (0.0, 5.0),
    "defend_line": (14.0, 24.0),
    "back_tank": (0.0, 1.0),
    "support_elixir": (1.0, 7.0),
    "cost_weight": (0.0, 0.8),
    "leak_guard": (8.5, 10.0),
    "spell_tower_bonus": (0.0, 3.0),
}
# Trophy counts the candidates are evaluated at: weighted toward the hard top end,
# since that is where the climb stalls.
EVAL_TROPHIES = (3000, 5500, 7500, 9000)


def _eval_one(args):
    agent, params, deck_name, level, trophies, seed = args
    rng = random.Random(seed)
    opp, opp_deck, opp_level = opponent_for(trophies, rng)
    r = Battle([DECKS[deck_name], opp_deck], [AGENTS[agent](params), opp],
               levels=(level, opp_level), seed=rng.randrange(1 << 30)).run()
    delta = WIN_TROPHIES if r.winner == 0 else (-LOSS_TROPHIES if r.winner == 1 else 0)
    return r.winner == 0, delta, r.duration


def evaluate(cands, level, games, seed, pool, agent="planner"):
    """Score candidates on identical opponent seeds (common random numbers)."""
    jobs, index = [], []
    for ci, (params, deck) in enumerate(cands):
        for g in range(games):
            trophies = EVAL_TROPHIES[g % len(EVAL_TROPHIES)]
            jobs.append((agent, params, deck, level, trophies, seed * 100003 + g))
            index.append(ci)
    results = pool.map(_eval_one, jobs, chunksize=4)
    stats = [[0, 0, 0.0] for _ in cands]
    for ci, (won, delta, dur) in zip(index, results):
        stats[ci][0] += won
        stats[ci][1] += delta
        stats[ci][2] += dur
    scores = []
    for wins, delta, dur in stats:
        win_rate = wins / games
        # Trophies per hour of play: the efficiency we maximise.
        tph = delta / ((dur + MATCH_OVERHEAD * games) / 3600)
        scores.append({"win_rate": win_rate, "trophies_per_hour": tph})
    return scores


def mutate(params, rng, scale):
    out = dict(params)
    for k, (lo, hi) in PARAM_RANGES.items():
        if rng.random() < 0.5:
            out[k] = min(hi, max(lo, out[k] + rng.gauss(0, scale * (hi - lo))))
    return out


def tune(generations=8, population=16, games=48, level=11.0, seed=0,
         workers=None, decks=None, agent="planner", start=None, log=print):
    rng = random.Random(seed)
    decks = decks or sorted(DECKS)
    pool = Pool(workers or os.cpu_count())
    try:
        cands = [(dict(DEFAULT_PARAMS), d) for d in decks]
        if start:
            # Continue from a previous result (e.g. the saved best strategy).
            cands.insert(0, (dict(start["params"]), start["deck"]))
        while len(cands) < population:
            base = start["params"] if start else DEFAULT_PARAMS
            cands.append((mutate(base, rng, 0.3), rng.choice(decks)))
        elite, best = [], None
        for gen in range(generations):
            scores = evaluate(cands, level, games, seed + gen, pool, agent)
            ranked = sorted(zip(scores, cands), key=lambda x: -x[0]["trophies_per_hour"])
            # Re-evaluate survivors each generation so lucky scores don't stick.
            elite = ranked[: max(2, population // 4)]
            best = elite[0]
            log(f"gen {gen + 1}/{generations}: best {best[1][1]:15s} "
                f"win {best[0]['win_rate']:.0%} "
                f"{best[0]['trophies_per_hour']:+.0f} trophies/h | "
                f"decks in elite: {sorted({c[1] for _, c in elite})}")
            cands = [c for _, c in elite]
            scale = 0.25 * (1 - gen / generations) + 0.05
            while len(cands) < population:
                params, deck = rng.choice(elite)[1]
                if rng.random() < 0.15:
                    deck = rng.choice(decks)
                cands.append((mutate(params, rng, scale), deck))
        # Final, larger evaluation of the elite to pick a robust winner.
        # The untuned defaults for each elite deck are included as a baseline.
        final = [c for _, c in elite]
        final += [(dict(DEFAULT_PARAMS), d) for d in sorted({c[1] for c in final})]
        scores = evaluate(final, level, games * 4, seed + 999, pool, agent)
        s, (params, deck) = max(zip(scores, final), key=lambda x: x[0]["trophies_per_hour"])
    finally:
        pool.close()
        pool.join()
    return {"agent": agent, "deck": deck, "cards": DECKS[deck], "params": params,
            "win_rate": s["win_rate"], "trophies_per_hour": s["trophies_per_hour"]}


def save(strategy, path):
    with open(path, "w") as f:
        json.dump(strategy, f, indent=2)


def load(path):
    with open(path) as f:
        return json.load(f)
