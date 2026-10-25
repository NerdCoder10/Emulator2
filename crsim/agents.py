"""Agents that play the simulator.

All agents work in local coordinates (own king tower at the bottom, y = 3).
"""
import math
import random

from .engine import Action, Battle, RIVER_LO, ELIXIR_PERIOD, MAX_ELIXIR, START_ELIXIR, \
    TOWER_STATS, AGENT_INTERVAL, DT, HEIGHT

LANE_X = {"left": 3.5, "right": 14.5}
TOWER_DPS = TOWER_STATS["princess"]["damage"] / TOWER_STATS["princess"]["hit_speed"]


def lane_of(x):
    return "left" if x < 9 else "right"


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class _Probe:
    """Stand-in for one of our units when scoring enemy counters against it."""

    def __init__(self, card):
        self.card = card
        self.hp = self.max_hp = card.total_hp
        self.air = card.air


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
    # Tactics taken from pro/creator guides (flags: > 0.5 means on).
    # Measured at 8,500-9,000 trophies: counter-push helps; the other three cost
    # elixir the defence needs and are off by default.
    "g_cycle": 0.0,           # count the opponent's cycle; push when their counter is out
    "g_punish": 0.0,          # opponent spends big -> push the opposite lane now
    "g_counterpush": 1.0,     # put the attacker behind surviving defenders
    "g_x2_bridge": 0.0,       # in double elixir, tanks go to the bridge, not the back
    "punish_spend": 6.0,      # enemy elixir spent in the last 4 s that opens a punish
    "punish_min_elixir": 5.0, # our elixir needed to punish
    "counter_threshold": 0.8, # matchup score at which an enemy card "counters" ours
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
        self.opp_order = []         # cards the opponent played, oldest first
        self.opp_spends = []        # (time, cost) of opponent plays

    # ------------------------------------------------------------------ utilities
    def _track_enemy(self, obs):
        dt = obs.time - self.last_t if self.last_t >= 0 else 0.0
        self.last_t = obs.time
        self.enemy_elixir = min(MAX_ELIXIR,
                                self.enemy_elixir + dt / ELIXIR_PERIOD * obs.elixir_mult)
        for card, x, y in obs.enemy_plays:
            self.enemy_elixir = max(0.0, self.enemy_elixir - card.cost)
            self.opp_order.append(card)
            self.opp_spends.append((obs.time, card.cost, x))

    # ------------------------------------------------------------------ guide tactics
    def _opp_hand(self):
        """The opponent's current hand, once all 8 of their cards have been seen.

        Played cards go to the back of a 4-card queue, so the last 4 plays are
        exactly the cards they cannot play right now.
        """
        deck = {c.name: c for c in self.opp_order}
        if len(deck) < 8:
            return None
        out = {c.name for c in self.opp_order[-4:]}
        return [c for n, c in deck.items() if n not in out]

    def _counter_in_hand(self, card):
        """Can the opponent answer `card` well with what they hold right now?"""
        hand = self._opp_hand()
        if hand is None:
            return True
        probe = [_Probe(card)]
        for c in hand:
            if c.cost <= self.enemy_elixir + 1 and \
                    (c.kind == "spell" and card.count >= 3 or
                     self._matchup(c, probe) >= self.p["counter_threshold"]):
                return True
        return False

    def _attackers(self, hand, elixir):
        """Cards that can carry an attack: win conditions, else tanks/heavy hitters."""
        cards = [c for c in hand if c.kind == "troop" and c.cost <= elixir]
        wins = [c for c in cards if c.is_win_condition]
        return wins or [c for c in cards if "tank" in c.roles or
                        ("dps" in c.roles and c.cost >= 4)]

    def _guide_offense(self, obs, threats):
        p, hand, elixir = self.p, obs.hand, obs.elixir
        on = lambda k: p[k] > 0.5
        attackers = self._attackers(hand, elixir)
        if not attackers:
            return None
        card = max(attackers, key=lambda c: (c.is_win_condition, c.total_hp))
        et = obs.enemy_towers
        weak = min(("left", "right"),
                   key=lambda l: (et[l].hp / et[l].max_hp) if et[l].alive else -1.0)

        # Counter-push: survivors near the river carry the attacker in for free.
        if on("g_counterpush") and not threats:
            survivors = [u for u in obs.my_units if u.kind == "troop" and u.card
                         and u.hp > 0.5 * u.max_hp and 10.0 <= u.y <= 18.0]
            if sum(u.card.cost / u.card.count for u in survivors) >= 3:
                lead = max(survivors, key=lambda u: u.y)
                y = clamp(lead.y - 1.5, 1.0, RIVER_LO)
                return Action(card.name, clamp(lead.x, 0.5, 17.5), y)

        # Punish: they just spent big, so hit the lane they are not in.
        recent = sum(c for t, c, _ in self.opp_spends if obs.time - t <= 4.0)
        if on("g_punish") and recent >= p["punish_spend"] and \
                elixir >= max(p["punish_min_elixir"], card.cost):
            their = [u.x for u in obs.enemy_units if u.kind == "troop"]
            lane = weak
            if their:
                lane = "right" if sum(their) / len(their) < 9 else "left"
            return Action(card.name, LANE_X[lane], 14.0)

        # Out of cycle: their answer to our attacker is not in hand.
        if on("g_cycle") and not threats and elixir >= card.cost + 1 and \
                not self._counter_in_hand(card):
            return Action(card.name, LANE_X[weak], 14.0)
        return None

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

    def _threats(self, obs):
        return [u for u in obs.enemy_units
                if u.kind == "troop" and u.y < self.p["defend_line"]]

    def _decide(self, obs):
        # 1. Value spells.
        spell = self._best_spell(obs)
        if spell is not None:
            _, card, x, y = spell
            return Action(card.name, x, y)
        threats = self._threats(obs)
        return self._defend(obs, threats) or self._offense(obs, threats)

    def _defend(self, obs, threats):
        """2. Defence: answer the most advanced push that the towers can't handle."""
        hand, elixir, p = obs.hand, obs.elixir, self.p
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
        return None

    def _offense(self, obs, threats):
        """Steps 3-5: support a push, start an attack, or avoid leaking elixir."""
        hand, elixir, p = obs.hand, obs.elixir, self.p
        guided = self._guide_offense(obs, threats)
        if guided is not None:
            return guided
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
            x2_bridge = p["g_x2_bridge"] > 0.5 and obs.elixir_mult >= 2
            if "tank" in card.roles and card.speed < 1.0 and p["back_tank"] > 0.5 \
                    and not x2_bridge:
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


PLANNER_PARAMS = {
    "horizon": 8.0,           # seconds simulated ahead for each candidate
    "plan_interval": 0.6,     # seconds between plans while nothing is played
    "tower_value": 3.0,       # elixir per 1000 tower hp
    "crown_value": 6.0,       # extra elixir-equivalent for taking a tower
    "danger": 0.0,            # extra weight on enemy units left in our half
    "min_gain": 0.3,          # a play must beat waiting by this much
    "max_candidates": 14,
    "model_opponent": 1.0,    # >0.5: the sandbox opponent answers with its inferred hand
    "model_delay": 0.6,       # seconds before the modelled opponent can respond
    "plan_attacks": 0.0,      # >0.5: also search attacks (tested: no gain, off)
    "attack_horizon": 12.0,   # seconds simulated for attack candidates
    "attack_interval": 1.0,   # seconds between attack searches
    "attack_min_elixir": 4.0, # don't search attacks below this elixir
}

# How the sandbox imagines the opponent: the plain heuristic, reacting a bit late.
MODEL_PARAMS = {"g_cycle": 0.0, "g_punish": 0.0, "g_counterpush": 0.0, "g_x2_bridge": 0.0}


class PlannerAgent(StrategicAgent):
    """StrategicAgent plus look-ahead search for defence and spells.

    Whenever enemy troops approach (or a spell might pay off), it rebuilds the
    visible board in a sandbox and simulates each candidate play, including
    waiting, a few seconds forward. It then makes the play with the best
    outcome: elixir kept, enemy elixir destroyed, tower hp kept and taken.
    Attacks still use the heuristic rules, since a sandbox opponent that never
    plays a card would make every attack look free.
    """
    name = "planner"

    def __init__(self, params=None, seed=None, mistake=0.0, reaction=0.0, plan=None):
        super().__init__(params, seed=seed, mistake=mistake, reaction=reaction)
        self.plan = dict(PLANNER_PARAMS)
        if plan:
            self.plan.update(plan)

    def reset(self, player):
        super().reset(player)
        self.next_plan = 0.0
        self.next_attack = 0.0
        self.my_spells = []         # spells in flight: [land, owner, card, x, y, mult]
        self.enemy_spells = []

    # ------------------------------------------------------------------ search
    @staticmethod
    def _mult(towers):
        t = towers["king"]
        return t.max_hp / TOWER_STATS["king"]["hp"]

    def _score(self, sb, start_towers):
        pl = self.plan
        v = sb.players[0].elixir
        for e in sb.entities:
            if e.kind == "tower":
                continue
            w = e.value * max(e.hp, 0.0) / e.max_hp
            if e.owner == 0:
                v += w
            else:
                v -= w * (1.0 + (pl["danger"] if e.y < HEIGHT / 2 else 0.0))
        for owner, sign in ((0, -1.0), (1, 1.0)):
            for role, hp0 in start_towers[owner].items():
                tw = sb.towers[owner].get(role)
                hp = max(tw.hp, 0.0) if tw is not None else 0.0
                v += sign * (hp0 - hp) / 1000.0 * pl["tower_value"]
                if hp0 > 0 and hp <= 0:
                    v += sign * pl["crown_value"]
        if sb.winner == 0:
            v += 100.0
        elif sb.winner == 1:
            v -= 100.0
        return v

    def _rollout(self, obs, card=None, x=0.0, y=0.0, horizon=None):
        sb = Battle.from_observation(obs, self.enemy_spells, self.my_spells)
        start = [{r: max(t.hp, 0.0) for r, t in sb.towers[o].items()} for o in (0, 1)]
        if self.plan["model_opponent"] > 0.5:
            self._add_opponent_model(sb, obs)
        if card is not None:
            sb.inject(0, card, x, y, self._mult(obs.my_towers))
            sb.players[0].elixir -= card.cost
        for _ in range(int((horizon or self.plan["horizon"]) / DT)):
            sb.step()
            if sb.winner is not None:
                break
        return self._score(sb, start)

    def _opp_cycle(self):
        """(hand, queue) the opponent most likely holds, from the plays seen so far.

        The last 4 distinct plays sit in the queue in order; every other card
        we have seen is in hand. Cards never seen are unknown and left out.
        """
        queue, names = [], set()
        for c in reversed(self.opp_order):
            if c.name not in names:
                names.add(c.name)
                queue.insert(0, c)
            if len(queue) == 4:
                break
        seen = {c.name: c for c in self.opp_order}
        hand = [c for n, c in seen.items() if n not in names][:4]
        return hand, queue

    def _add_opponent_model(self, sb, obs):
        hand, queue = self._opp_cycle()
        if not hand:
            return
        ps = sb.players[1]
        ps.hand, ps.queue = list(hand), list(queue) or list(hand)
        ps.elixir = self.enemy_elixir
        ps.level = 11 + math.log(self._mult(obs.enemy_towers)) / math.log(1.1)
        model = StrategicAgent(MODEL_PARAMS, reaction=0.4)
        model.reset(1)
        model.enemy_elixir = obs.elixir
        model.last_t = obs.time
        model.next_ok = obs.time + self.plan["model_delay"]   # time to react
        sb.agents = [IdleAgent(), model]

    def _candidates(self, obs, threats):
        cands = []
        hand = [c for c in obs.hand if c.cost <= obs.elixir]
        for card in hand:
            if card.kind == "spell":
                spots = []
                for u in obs.enemy_units:
                    spots.append((self._spell_value(card, u.x, u.y, obs), u.x, u.y))
                spots.sort(reverse=True)
                for val, x, y in spots[:2]:
                    if val >= 0.6 * card.cost:
                        cands.append((card, x, y))
                continue
            if not threats:
                continue
            seen = set()
            for lane, group in self._pushes(threats).items():
                if not group:
                    continue
                lead = min(group, key=lambda u: u.y)
                spots = [self._defense_spot(card, group, lane),
                         (lead.x, lead.y - 1.0), (lead.x, lead.y - 4.0)]
                if card.kind == "building":
                    spots.append((9.0, 8.0))
                for sx, sy in spots:
                    sx, sy = clamp(sx, 0.5, 17.5), clamp(sy, 0.5, RIVER_LO)
                    key = (round(sx), round(sy))
                    if key in seen or not obs.can_place(card, sx, sy):
                        continue
                    seen.add(key)
                    cands.append((card, sx, sy))
        return cands

    def _plan(self, obs, threats):
        return self._search(obs, self._candidates(obs, threats), self.plan["horizon"])

    def _search(self, obs, cands, horizon):
        """Simulate each candidate (and waiting); return the best that beats waiting."""
        if not cands:
            return None
        cands = cands[: int(self.plan["max_candidates"])]
        base = self._rollout(obs, horizon=horizon)
        best, best_v = None, base + self.plan["min_gain"]
        for card, x, y in cands:
            v = self._rollout(obs, card, x, y, horizon=horizon)
            if v > best_v:
                best, best_v = (card, x, y), v
        return best

    def _attack_candidates(self, obs):
        """Attacks worth simulating: each troop at each bridge or pocket, tanks also
        behind the king tower, and anything behind units already pushing."""
        et = obs.enemy_towers
        cands = []
        pushers = [u for u in obs.my_units if u.kind == "troop" and u.card
                   and u.hp > 0.5 * u.max_hp and 8.0 <= u.y <= 24.0]
        lead = max(pushers, key=lambda u: u.y) if pushers else None
        for card in obs.hand:
            if card.kind != "troop" or card.cost > obs.elixir or "cycle" in card.roles:
                continue
            for lane in ("left", "right"):
                lx = LANE_X[lane]
                if et[lane].alive:
                    cands.append((card, lx, 14.0))
                else:
                    cands.append((card, lx + (1.5 if lane == "left" else -1.5), 20.5))
                if "tank" in card.roles and card.speed < 1.0:
                    cands.append((card, lx + (1.0 if lane == "left" else -1.0), 1.5))
            if lead is not None:
                y = clamp(lead.y - (3.0 if card.is_ranged else 1.5), 0.5, RIVER_LO)
                if obs.can_place(card, lead.x, y):
                    cands.append((card, clamp(lead.x, 0.5, 17.5), y))
        return cands

    # ------------------------------------------------------------------ main loop
    def _track_spells(self, obs):
        em = self._mult(obs.enemy_towers)
        for card, x, y in obs.enemy_plays:
            if card.kind == "spell":
                self.enemy_spells.append([obs.time + card.travel, 1, card, x, y, em])
        self.enemy_spells = [s for s in self.enemy_spells if s[0] > obs.time]
        self.my_spells = [s for s in self.my_spells if s[0] > obs.time]

    def act(self, obs):
        self._track_spells(obs)
        action = super().act(obs)
        if action is not None:
            card = next(c for c in obs.hand if c.name == action.card)
            if card.kind == "spell":
                self.my_spells.append([obs.time + card.travel, 0, card, action.x, action.y,
                                       self._mult(obs.my_towers)])
        return action

    def _decide(self, obs):
        threats = self._threats(obs)
        if (threats or obs.enemy_units) and obs.time >= self.next_plan:
            choice = self._plan(obs, threats)
            if choice is not None:
                card, x, y = choice
                return Action(card.name, x, y)
            self.next_plan = obs.time + self.plan["plan_interval"]
        if threats:
            return None
        pl = self.plan
        if pl["plan_attacks"] > 0.5 and pl["model_opponent"] > 0.5 and \
                len(self._opp_cycle()[0]) >= 2 and obs.elixir >= pl["attack_min_elixir"]:
            if obs.time >= self.next_attack:
                self.next_attack = obs.time + pl["attack_interval"]
                choice = self._search(obs, self._attack_candidates(obs), pl["attack_horizon"])
                if choice is not None:
                    card, x, y = choice
                    return Action(card.name, x, y)
            if obs.elixir < self.p["leak_guard"]:
                return None
        return self._offense(obs, threats)


AGENTS = {
    "idle": IdleAgent,
    "random": RandomAgent,
    "simple": SimpleAgent,
    "strategic": StrategicAgent,
    "planner": PlannerAgent,
}
