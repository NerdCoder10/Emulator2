"""Agents that play the simulator.

All agents work in local coordinates (own king tower at the bottom, y = 3).
"""
import math
import random

from .engine import Action, RIVER_LO, ELIXIR_PERIOD, MAX_ELIXIR, START_ELIXIR, \
    TOWER_STATS, AGENT_INTERVAL

LANE_X = {"left": 3.5, "right": 14.5}
TOWER_DPS = TOWER_STATS["princess"]["damage"] / TOWER_STATS["princess"]["hit_speed"]


def lane_of(x):
    return "left" if x < 9 else "right"


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Agent:
    name = "agent"

    def reset(self, player):
        self.player = player

    def act(self, obs):
        raise NotImplementedError


class IdleAgent(Agent):
    name = "idle"

    def act(self, obs):
        return None


class RandomAgent(Agent):
    """Plays a random affordable card at a random legal spot."""
    name = "random"

    def __init__(self, seed=None, patience=0.3):
        self.rng = random.Random(seed)
        self.patience = patience

    def act(self, obs):
        if self.rng.random() > self.patience * AGENT_INTERVAL:
            return None
        cards = [c for c in obs.hand if c.cost <= obs.elixir]
        if not cards:
            return None
        c = self.rng.choice(cards)
        if c.kind == "spell":
            if not obs.enemy_units:
                return None
            u = self.rng.choice(obs.enemy_units)
            return Action(c.name, u.x, u.y)
        return Action(c.name, self.rng.uniform(1, 17), self.rng.uniform(1, 14.5))


class SimpleAgent(Agent):
    """A beginner human: drops troops on whatever invades, otherwise spams the
    bridge once elixir is full."""
    name = "simple"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def act(self, obs):
        affordable = [c for c in obs.hand if c.cost <= obs.elixir and c.kind != "spell"]
        threats = [u for u in obs.enemy_units if u.y < 14 and not u.deploying]
        if threats and affordable and self.rng.random() < 0.25:
            u = min(threats, key=lambda u: u.y)
            c = self.rng.choice(affordable)
            return Action(c.name, clamp(u.x, 0.5, 17.5), clamp(u.y - 1, 0.5, 14.5))
        if obs.elixir >= 9.5 and affordable:
            c = self.rng.choice(affordable)
            lane = self.rng.choice(("left", "right"))
            return Action(c.name, LANE_X[lane], 13.5)
        spells = [c for c in obs.hand if c.kind == "spell" and c.cost <= obs.elixir]
        if spells and len(obs.enemy_units) >= 4 and self.rng.random() < 0.1:
            u = self.rng.choice(obs.enemy_units)
            return Action(spells[0].name, u.x, u.y)
        return None


DEFAULT_PARAMS = {
    "attack_elixir": 8.5,     # start a push once we have this much elixir
    "punish_elixir": 3.0,     # ...or when the opponent is estimated to be this low
    "spell_ratio": 1.15,      # cast a spell if it destroys >= ratio * its cost
    "tower_tolerance": 1.6,   # let towers handle threats worth <= this elixir
    "defend_line": 19.0,      # react to enemies whose local y is below this
    "back_tank": 1.0,         # >0.5: place slow tanks behind the king tower
    "support_elixir": 3.0,    # elixir needed to add support to a push
    "cost_weight": 0.25,      # how strongly defensive picks prefer cheap cards
    "leak_guard": 9.6,        # never sit above this elixir
    "spell_tower_bonus": 1.0, # weight of chip damage when valuing spells
}


class StrategicAgent(Agent):
    """Heuristic player built around elixir trades.

    Priorities each decision tick:
      1. Spells that kill more elixir than they cost (or finish a tower).
      2. Defence: cheapest card that wins the matchup vs. the invading push.
      3. Support an existing push (counter-push).
      4. Attack with the win condition in the weaker lane when elixir is high
         or the opponent just over-committed.
      5. Never leak elixir.
    """
    name = "strategic"

    def __init__(self, params=None, seed=None, mistake=0.0, reaction=0.0):
        self.p = dict(DEFAULT_PARAMS)
        if params:
            self.p.update(params)
        self.rng = random.Random(seed)
        self.mistake = mistake      # probability a decision is botched/skipped
        self.reaction = reaction    # extra seconds between decisions

    def reset(self, player):
        self.player = player
        self.enemy_elixir = START_ELIXIR
        self.last_t = -1.0
        self.next_ok = 0.0
        self.handled = {}           # enemy unit id -> time we last answered it

    # ------------------------------------------------------------------ utilities
    def _track_enemy(self, obs):
        dt = obs.time - self.last_t if self.last_t >= 0 else 0.0
        self.last_t = obs.time
        self.enemy_elixir = min(MAX_ELIXIR,
                                self.enemy_elixir + dt / ELIXIR_PERIOD * obs.elixir_mult)
        for card, _, _ in obs.enemy_plays:
            self.enemy_elixir = max(0.0, self.enemy_elixir - card.cost)

    @staticmethod
    def _pushes(units):
        """Group enemy units into per-lane pushes."""
        groups = {"left": [], "right": []}
        for u in units:
            groups[lane_of(u.x)].append(u)
        return groups

    def _matchup(self, card, threats):
        """How well `card` answers a group of enemy units (higher is better)."""
        if card.kind == "spell":
            return -1.0
        hp_ground = sum(u.hp for u in threats if not u.air)
        hp_air = sum(u.hp for u in threats if u.air)
        if hp_air > 0 and not card.can_hit_air and card.kind != "building":
            if hp_ground == 0:
                return -1.0
        if card.targets == "buildings":
            # Win conditions only tank/distract; poor defenders.
            return 0.2 - card.cost * self.p["cost_weight"]
        n_threat = len(threats)
        reach = hp_ground + (hp_air if card.can_hit_air else 0)
        my_dps = card.dps
        if card.splash and n_threat >= 3:
            my_dps *= min(n_threat, 6) * 0.6
        kill_time = reach / max(my_dps, 1.0)
        enemy_dps = 0.0
        pulls = False
        for u in threats:
            c = u.card
            if c is None:
                continue
            if c.targets == "buildings":
                pulls = True
                continue
            if u.air and not card.can_hit_air:
                continue
            d = c.damage / c.hit_speed
            if c.splash and card.count >= 3:
                d *= min(card.count, 6) * 0.6
            enemy_dps += d
        die_time = card.total_hp / max(enemy_dps, 1.0)
        score = min(die_time / max(kill_time, 0.1), 3.0)
        if card.kind == "building":
            score = score + 1.5 if pulls else score * 0.6
        if not card.can_hit_air and hp_air > 0:
            score *= hp_ground / (hp_ground + hp_air)
        return score - card.cost * self.p["cost_weight"]

    def _defended_value(self, obs, group):
        """Elixir worth of our units already positioned to fight `group`."""
        has_air = any(u.air for u in group)
        has_ground = any(not u.air for u in group)
        pulls = any(u.card and u.card.targets == "buildings" for u in group)
        total = 0.0
        for m in obs.my_units:
            c = m.card
            if c is None or c.targets == "buildings":
                continue
            if not ((has_ground) or (has_air and c.can_hit_air)):
                continue
            near = min(math.hypot(m.x - u.x, m.y - u.y) for u in group)
            reach = 7.0 if m.kind == "building" else 6.0
            if near > reach:
                continue
            w = 1.5 if (m.kind == "building" and pulls) else 1.0
            total += w * c.cost / c.count * m.hp / m.max_hp
        return total

    def _defense_spot(self, card, threats, lane):
        lead = min(threats, key=lambda u: u.y)
        lx = LANE_X[lane]
        tx, ty = lead.x, lead.y
        if card.kind == "building":
            return (7.5 if lane == "left" else 10.5), 9.0
        if card.is_ranged:
            x = lx + (2.0 if lane == "left" else -2.0)
            return x, clamp(min(ty - card.range + 1.0, 8.0), 2.0, RIVER_LO)
        if ty > RIVER_LO:
            # Meet the push at the bridge.
            return lx, 12.5
        return clamp(tx, 0.5, 17.5), clamp(ty - 1.5, 0.5, RIVER_LO)

    def _spell_value(self, card, x, y, obs):
        value = 0.0
        for u in obs.enemy_units:
            if math.hypot(u.x - x, u.y - y) > card.radius:
                continue
            dealt = min(u.hp, card.damage)
            per_unit = (u.card.cost / u.card.count) if u.card else 1.0
            value += per_unit * dealt / u.max_hp
            if dealt >= u.hp:
                value += 0.25 * per_unit
        for tw in obs.enemy_towers.values():
            if tw.alive and math.hypot(tw.x - x, tw.y - y) <= card.radius + 1.0:
                tdmg = card.damage * card.tower_pct
                if tdmg >= tw.hp:
                    value += 50.0
                value += self.p["spell_tower_bonus"] * 6.0 * tdmg / tw.max_hp
        return value

    def _best_spell(self, obs):
        best = None
        for card in obs.hand:
            if card.kind != "spell" or card.cost > obs.elixir:
                continue
            spots = []
            for u in obs.enemy_units:
                # Lead moving troops: they walk toward our towers (down in local y).
                lead = 0.0 if (u.kind != "troop" or u.deploying) else \
                    (u.card.speed * card.travel if u.card else 0.0)
                spots.append((u.x, u.y - lead))
            spots += [(tw.x, tw.y) for tw in obs.enemy_towers.values() if tw.alive]
            for x, y in spots:
                v = self._spell_value(card, x, y, obs)
                if v >= card.cost * self.p["spell_ratio"] and \
                        (best is None or v - card.cost > best[0]):
                    best = (v - card.cost, card, x, y)
        return best

    # ------------------------------------------------------------------ main loop
    def act(self, obs):
        self._track_enemy(obs)
        if obs.time < self.next_ok:
            return None
        action = self._decide(obs)
        if action is not None:
            if self.mistake and self.rng.random() < self.mistake:
                self.next_ok = obs.time + 1.0 + self.rng.random() * 2
                if self.rng.random() < 0.5:
                    return None
                # Botched placement.
                action = Action(action.card,
                                clamp(action.x + self.rng.uniform(-4, 4), 0.5, 17.5),
                                clamp(action.y + self.rng.uniform(-4, 4), 0.5, 14.5))
            self.next_ok = obs.time + self.reaction
        return action

    def _decide(self, obs):
        hand = obs.hand
        elixir = obs.elixir
        p = self.p

        # 1. Value spells.
        spell = self._best_spell(obs)
        if spell is not None:
            _, card, x, y = spell
            return Action(card.name, x, y)

        # 2. Defence.
        threats = [u for u in obs.enemy_units
                   if u.kind == "troop" and u.y < p["defend_line"]]
        pushes = self._pushes(threats)
        for lane in sorted(pushes, key=lambda l: min((u.y for u in pushes[l]),
                                                     default=99)):
            group = pushes[lane]
            if not group:
                continue
            threat_value = sum(u.card.cost / u.card.count * u.hp / u.max_hp
                               for u in group if u.card)
            if threat_value <= p["tower_tolerance"] or \
                    threat_value <= self._defended_value(obs, group):
                continue
            options = []
            for card in hand:
                if card.cost > elixir:
                    continue
                s = self._matchup(card, group)
                if s > 0:
                    options.append((s, card))
            if not options:
                continue
            _, card = max(options, key=lambda o: o[0])
            x, y = self._defense_spot(card, group, lane)
            return Action(card.name, x, y)

        # 3. Support an existing push.
        pushers = [u for u in obs.my_units
                   if u.kind == "troop" and u.card and u.hp > 0.4 * u.max_hp
                   and 9.0 <= u.y <= 27.0]
        if pushers and elixir >= p["support_elixir"]:
            lead = max(pushers, key=lambda u: u.card.total_hp * u.hp / u.max_hp)
            supports = [c for c in hand if c.kind == "troop" and not c.is_win_condition
                        and c.cost <= elixir - 0.0 and "cycle" not in c.roles]
            push_value = sum(u.card.cost / u.card.count for u in pushers)
            if supports and push_value >= 3 and not obs.enemy_units:
                card = max(supports, key=lambda c: (c.is_ranged, c.dps / c.cost))
                if elixir >= card.cost + 1 or elixir >= p["attack_elixir"]:
                    y = clamp(lead.y - (3.0 if card.is_ranged else 1.5), 1.0, RIVER_LO)
                    return Action(card.name, clamp(lead.x, 0.5, 17.5), y)

        # 4. Attack.
        et = obs.enemy_towers
        lanes = [l for l in ("left", "right")]
        target_lane = min(lanes, key=lambda l: (et[l].hp / et[l].max_hp) if et[l].alive
                          else -1.0)
        pocket = not et[target_lane].alive
        wins = [c for c in hand if c.is_win_condition and c.cost <= elixir]
        ready = elixir >= p["attack_elixir"] or \
            (self.enemy_elixir <= p["punish_elixir"] and wins)
        if ready and wins and not threats:
            card = max(wins, key=lambda c: c.total_hp)
            lx = LANE_X[target_lane]
            if pocket:
                return Action(card.name, lx + (1.5 if target_lane == "left" else -1.5), 20.5)
            if "tank" in card.roles and card.speed < 1.0 and p["back_tank"] > 0.5:
                return Action(card.name, lx + (1.0 if target_lane == "left" else -1.0), 1.5)
            if card.air:
                return Action(card.name, lx, 13.0)
            return Action(card.name, lx, 14.0)

        # 5. Leak guard: cycle a cheap card somewhere safe.
        if elixir >= p["leak_guard"]:
            troops = [c for c in hand if c.kind == "troop" and not c.is_win_condition]
            if troops:
                card = min(troops, key=lambda c: c.cost)
                lx = LANE_X[target_lane]
                return Action(card.name, lx + (1.0 if target_lane == "left" else -1.0), 2.0)
            cheap = [c for c in hand if c.kind == "troop"]
            if cheap:
                card = min(cheap, key=lambda c: c.cost)
                return Action(card.name, LANE_X[target_lane], 14.0)
        return None


AGENTS = {
    "idle": IdleAgent,
    "random": RandomAgent,
    "simple": SimpleAgent,
    "strategic": StrategicAgent,
}
