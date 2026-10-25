"""Trophy-road simulation: how far does an agent climb, and how fast?"""
import random
from dataclasses import dataclass, field

from .agents import RandomAgent, SimpleAgent, StrategicAgent
from .cards import DECKS
from .engine import Battle

ARENAS = [
    (0, "Goblin Stadium"), (300, "Bone Pit"), (600, "Barbarian Bowl"),
    (1000, "Spell Valley"), (1300, "Builder's Workshop"), (1600, "P.E.K.K.A's Playhouse"),
    (2000, "Royal Arena"), (2300, "Frozen Peak"), (2600, "Jungle Arena"),
    (3000, "Hog Mountain"), (3400, "Electro Valley"), (3800, "Spooky Town"),
    (4200, "Rascal's Hideout"), (4600, "Serenity Peak"), (5000, "Miner's Mine"),
    (5500, "Executioner's Kitchen"), (6000, "Royal Crypt"), (6500, "Silent Sanctuary"),
    (7000, "Dragon Spa"), (7500, "Clash Fest"), (8000, "PANCAKES!"),
    (9000, "Legendary Arena"),
]
GATE_LIMIT = 5000          # arenas below this have trophy gates (cannot drop out)
TROPHY_CAP = 9000.0        # trophy count at which opponents are at full strength
WIN_TROPHIES, LOSS_TROPHIES = 30, 30
# Ladder opponents play the original heuristic, without the guide tactics,
# so the difficulty curve stays fixed while our AI improves.
OPPONENT_PARAMS = {"g_cycle": 0.0, "g_punish": 0.0, "g_counterpush": 0.0,
                   "g_x2_bridge": 0.0}
MATCH_OVERHEAD = 45.0      # seconds of matchmaking/loading per battle


def arena_for(trophies):
    name = ARENAS[0][1]
    for floor, n in ARENAS:
        if trophies >= floor:
            name = n
    return name


def gate_for(trophies):
    gate = 0
    for floor, _ in ARENAS:
        if floor <= trophies and floor < GATE_LIMIT:
            gate = floor
    return gate


def opponent_for(trophies, rng):
    """Build an opponent whose skill and card levels scale with trophies."""
    s = min(max(trophies / TROPHY_CAP, 0.0), 1.0)
    deck = DECKS[rng.choice(sorted(DECKS))]
    level = 9.0 + 5.0 * s
    seed = rng.randrange(1 << 30)
    roll = rng.random()
    if trophies < 300 and roll < 0.5:
        agent = RandomAgent(seed=seed, patience=1.0)
    elif roll < max(0.0, 0.9 - 2.5 * s):
        agent = SimpleAgent(seed=seed)
    else:
        agent = StrategicAgent(OPPONENT_PARAMS, seed=seed, mistake=0.45 * (1 - s) ** 1.5 + 0.03,
                               reaction=1.2 * (1 - s) + 0.2)
    return agent, deck, level


@dataclass
class LadderReport:
    battles: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    trophies: int = 0
    peak: int = 0
    three_crowns: int = 0
    play_seconds: float = 0.0
    history: list = field(default_factory=list)

    @property
    def win_rate(self):
        return self.wins / self.battles if self.battles else 0.0

    @property
    def trophies_per_hour(self):
        hours = (self.play_seconds + MATCH_OVERHEAD * self.battles) / 3600
        return self.trophies / hours if hours else 0.0

    def summary(self):
        return (f"battles={self.battles} W/L/D={self.wins}/{self.losses}/{self.draws} "
                f"win_rate={self.win_rate:.1%} three_crowns={self.three_crowns}\n"
                f"final trophies={self.trophies} ({arena_for(self.trophies)}) "
                f"peak={self.peak} ({arena_for(self.peak)})\n"
                f"efficiency={self.trophies_per_hour:.0f} trophies/hour "
                f"({self.peak / max(self.battles, 1):.1f} peak trophies/battle)")


def run_ladder(make_agent, deck, level=11.0, battles=300, seed=0, start=0,
               plateau=60, log=None):
    """Climb the ladder until `battles` are played or no new peak for `plateau` battles."""
    rng = random.Random(seed)
    rep = LadderReport(trophies=start, peak=start)
    since_peak = 0
    for i in range(battles):
        opp, opp_deck, opp_level = opponent_for(rep.trophies, rng)
        r = Battle([deck, opp_deck], [make_agent(), opp], levels=(level, opp_level),
                   seed=rng.randrange(1 << 30)).run()
        rep.battles += 1
        rep.play_seconds += r.duration
        if r.winner == 0:
            rep.wins += 1
            rep.trophies += WIN_TROPHIES
            rep.three_crowns += r.crowns[0] == 3
        elif r.winner == 1:
            rep.losses += 1
            rep.trophies = max(gate_for(rep.trophies), rep.trophies - LOSS_TROPHIES)
        else:
            rep.draws += 1
        rep.history.append(rep.trophies)
        if rep.trophies > rep.peak:
            rep.peak = rep.trophies
            since_peak = 0
        else:
            since_peak += 1
        if log and (i + 1) % 25 == 0:
            log(f"  battle {i + 1:4d}: {rep.trophies:5d} trophies ({arena_for(rep.trophies)}), "
                f"win rate {rep.win_rate:.0%}")
        if plateau and since_peak >= plateau:
            break
    return rep
