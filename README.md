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

# Search for the most trophy-efficient deck + strategy (about 3 min on 4 cores)
python main.py tune --out best_strategy.json

# Climb the trophy road with the tuned strategy and report how far it gets
python main.py ladder --battles 400

# Tests
python -m unittest discover -s tests -t .
```

## How it works

| Module | What it does |
| --- | --- |
| `crsim/cards.py` | 23 cards (troops, buildings, spells) with approximate level-11 stats, plus 6 decks |
| `crsim/engine.py` | 18×32 arena with 0.1 s ticks: towers, king activation, elixir (1×, 2×, 3×), bridges and river pathing, targeting (ground/air/buildings), splash, spells, building decay, 3 min regulation plus 2 min sudden-death overtime and a tiebreaker |
| `crsim/agents.py` | `RandomAgent`, `SimpleAgent` (a beginner), and `StrategicAgent` (the AI) |
| `crsim/ladder.py` | Trophy road: 22 arenas, trophy gates, and opponents whose skill and card level (9 to 14) grow with trophies |
| `crsim/tune.py` | Parallel evolutionary search over deck choice and 10 strategy parameters, scored on **trophies per hour** against high-ladder opponents |
| `crsim/replay.py` | Self-contained HTML/canvas replay viewer |

### The AI (`StrategicAgent`)
Each decision tick (every 0.2 s) it works through these steps in order:
1. **Value spells**: cast when the spell destroys at least `spell_ratio` times its cost in elixir, or to finish a tower.
2. **Defence**: group invaders by lane, skip pushes the towers or existing units already handle, and otherwise pick the cheapest card that wins the matchup (DPS against effective HP, splash against swarms, buildings to pull building-targeters, anti-air), then place it according to its role.
3. **Counter-push**: add ranged or high-DPS support behind surviving units.
4. **Attack**: play the win condition in the weaker lane, or the pocket once a tower is down, when elixir is high or the estimated opponent elixir is low (it tracks the opponent's spending).
5. **Leak guard**: never sit at full elixir.

### Efficiency metric
Net trophies / (battle time + 45 s overhead per match). Fast 3-crown wins
score better than slow overtime wins.

## Results (level-11 cards, seeds 0–3, 400 battles each)

| Strategy | Deck | Peak trophies | Arena |
| --- | --- | --- | --- |
| Default parameters | pekka_control | 6480–6660 | Royal Crypt / Silent Sanctuary |
| Tuned (`best_strategy.json`) | pekka_control | 6480–6810 | up to Silent Sanctuary |

The climb is fast at first (about 100% win rate up to 1,500 trophies, about 95%
up to 4,000). It then levels off around 6,500, where opponents play nearly
perfectly with level 13–14 cards against our level 11. Raise `--level` to see
how far better cards take it.
