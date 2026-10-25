# Emulator2: Clash Royale battle emulator and ladder-climbing AI

An offline, deterministic simulator of Clash Royale-style battles, an AI that
plays it, and an optimizer that tunes the AI's deck and strategy to climb the
trophy road as **far and as efficiently** (trophies per hour) as possible.

> This is a self-contained simulation. It does not connect to, automate, or
> interact with the real game; botting the live game breaks Supercell's ToS.

Pure Python 3.10+, no dependencies.

## Quick start

```bash
# One battle, with an HTML replay you can open in a browser
python main.py battle --opponent strategic --opponent-deck hog_cycle --replay replay.html

# Search for the most trophy-efficient deck + strategy (about 15 min on 4 cores)
python main.py tune --out best_strategy.json

# Climb the trophy road with the tuned strategy and report how far it gets
python main.py ladder --battles 600

# Record games across the ladder into one replay page (Battle Theater)
python main.py showcase --out battles.html

# Tests
python -m unittest discover -s tests -t .
```

## How it works

| Module | What it does |
| --- | --- |
| `crsim/cards.py` | 23 cards (troops, buildings, spells) with approximate level-11 stats, plus 6 decks |
| `crsim/engine.py` | 18×32 arena with 0.1 s ticks: towers, king activation, elixir (1×, 2×, 3×), bridges and river pathing, targeting (ground/air/buildings), splash, spells, building decay, 3 min regulation plus 2 min sudden-death overtime and a tiebreaker |
| `crsim/agents.py` | `RandomAgent`, `SimpleAgent` (a beginner), `StrategicAgent` (heuristic AI), and `PlannerAgent` (heuristic plus look-ahead search, the default) |
| `crsim/ladder.py` | Trophy road: 22 arenas, trophy gates, and opponents whose skill and card level (9 to 14) grow with trophies |
| `crsim/tune.py` | Parallel evolutionary search over deck choice and 10 strategy parameters, scored on **trophies per hour** against high-ladder opponents |
| `crsim/replay.py`, `crsim/viewer.html` | Battle Theater: a self-contained HTML replay page with several games, playback controls and play-by-play |

### The look-ahead AI (`PlannerAgent`)
When enemy troops approach, or a spell might pay off, the planner rebuilds
everything it can see in a sandbox (`Battle.from_observation`), including
spells already in flight. It then simulates each candidate play, plus
waiting, 8 seconds forward. Candidates are every affordable card at several
spots (the heuristic's spot, on the lead attacker, in front of it, and the
central building pull), plus spells on the most valuable clusters. Each
outcome is scored in elixir terms: elixir kept, unit value alive on each
side, tower hp lost and taken, and crowns. The best play is made only if it
beats waiting.

**Opponent model (cycle counting).** Inside each look-ahead the opponent is
not idle. The AI infers their hand from the cycle: the last 4 distinct cards
they played sit in their queue, and every other card seen so far is in hand.
It also tracks their elixir from their spending. A copy of the heuristic AI
then plays that hand for them, after a 0.6 s reaction delay. So a Skeleton
Army against a P.E.K.K.A scores badly when the opponent is holding Zap.

### The heuristic AI (`StrategicAgent`)
Each decision tick (every 0.2 s) it works through these steps in order:
1. **Value spells**: cast when the spell destroys at least `spell_ratio` times its cost in elixir, or to finish a tower.
2. **Defence**: group invaders by lane, skip pushes the towers or existing units already handle, and otherwise pick the cheapest card that wins the matchup (DPS against effective HP, splash against swarms, buildings to pull building-targeters, anti-air), then place it according to its role.
3. **Counter-push**: add ranged or high-DPS support behind surviving units.
4. **Attack**: play the win condition in the weaker lane, or the pocket once a tower is down, when elixir is high or the estimated opponent elixir is low (it tracks the opponent's spending).
5. **Leak guard**: never sit at full elixir.

### Strategies from creator and pro guides
YouTube blocks automated access, so video transcripts couldn't be read
directly. The tactics came from written guides that summarize what top
players and creators teach. Each was implemented as a switchable behaviour
and measured on 120–200 games at 8,500 and 9,000 trophies:

| Guide tactic | Where | Result |
| --- | --- | --- |
| Count the opponent's cycle and play around their answers | Opponent model in the planner | **Kept**: 8,500 win rate 50% → 57–59% |
| Counter-push with surviving defenders (`g_counterpush`) | Offense | **Kept**: removing it costs about 4 points |
| Push when their counter is out of cycle (`g_cycle`) | Offense | Off: no gain |
| Opponent spends 6+ → push the opposite lane (`g_punish`) | Offense | Off: no gain; it spends elixir the defence needs |
| Double elixir: tank at the bridge, not the back (`g_x2_bridge`) | Offense | Off: no gain |
| Simulating attacks against the modelled opponent (`plan_attacks`) | Planner | Off: no gain |

Sources: [TrophyCoach elixir guide](https://trophycoach.com/guides/elixir-management-mastery-guide),
[jeu.video timing guide](https://jeu.video/en/guide/clash-royale-ladder-save-elixir-push-right-time),
[Metafy card-counting guide](https://metafy.gg/guides/view/elixir-and-card-counting-pro-guide-MnGsVkzCxU5),
[Guild Order elixir wiki](https://guildorder.com/games/clash_royale/wiki/elixir-management-and-cycling),
[RoyaleTracker P.E.K.K.A guide](https://royaletracker.gg/guides/pekka-bridge-spam-deck-clash-royale),
[Clash Royale Wiki deck page](https://clashroyale.fandom.com/wiki/Deck:3M_Miner_Ram).

Ladder opponents keep the original heuristic (`OPPONENT_PARAMS` in
`crsim/ladder.py`), so the difficulty curve is the same in every result below.

### Efficiency metric
Net trophies / (battle time + 45 s overhead per match). Fast 3-crown wins
score better than slow overtime wins.

## Results (level-11 cards, P.E.K.K.A control, seeds 0–3)

| AI | Win rate at 8,500 | Win rate at 9,000 | Peak trophies | Arena |
| --- | --- | --- | --- | --- |
| Heuristic (`--agent strategic`), 500 battles | – | – | 6,480–6,810 | Royal Crypt / Silent Sanctuary |
| Planner, 500 battles | 51% | 40% | 8,070–8,430 | PANCAKES! |
| **Planner + opponent model + counter-push** (default), 600 battles | **60%** | **49%** | **8,820–9,240** | **PANCAKES! / Legendary Arena** |

Every run of the current AI passes 8,500 trophies, and one reaches Legendary
Arena (9,000+). The climb levels off near 9,000, where opponents have
level-14 cards against our level 11. A battle takes about 1 s to simulate
with the planner, versus 0.1 s for the heuristic.
