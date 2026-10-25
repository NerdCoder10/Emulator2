"""Deterministic, tick-based Clash Royale battle simulator.

World coordinates: the arena is 18 x 32 tiles. Player 0 owns the bottom half
(y < 16), player 1 the top half. Agents never see world coordinates directly:
observations and actions are expressed in the player's *local* frame, in which
the player always sits at the bottom (local y = world y for player 0, and
32 - world y for player 1).
"""
import math
import random
from dataclasses import dataclass, field

from .cards import CARDS, Card

DT = 0.1
WIDTH, HEIGHT = 18.0, 32.0
RIVER_Y = 16.0
RIVER_LO, RIVER_HI = 15.0, 17.0
BRIDGES = (3.5, 14.5)
REGULATION = 180.0
OVERTIME = 120.0
ELIXIR_PERIOD = 2.8
MAX_ELIXIR = 10.0
START_ELIXIR = 5.0
AGENT_INTERVAL = 0.2          # agents are polled 5x per second
LEVEL_BASE = 11

TOWER_STATS = {
    "princess": dict(hp=3052, damage=109, hit_speed=0.8, range=7.5, size=1.5),
    "king": dict(hp=4824, damage=109, hit_speed=1.0, range=7.0, size=2.0),
}
# Local positions of a player's own towers.
TOWER_LAYOUT = {"left": (3.5, 6.5), "right": (14.5, 6.5), "king": (9.0, 3.0)}
UNIT_SIZE = {"troop": 0.4, "building": 1.0}


def level_mult(level: float) -> float:
    return 1.1 ** (level - LEVEL_BASE)


def to_local(x, y, player):
    """Convert between world and player-local coordinates (an involution)."""
    return (x, y) if player == 0 else (x, HEIGHT - y)


class Entity:
    __slots__ = ("id", "owner", "card", "name", "kind", "x", "y", "hp", "max_hp",
                 "damage", "hit_speed", "range", "sight", "speed", "targets", "air",
                 "splash", "size", "cooldown", "target", "deploy", "decay",
                 "role", "active", "jumps", "value")

    def __init__(self, eid, owner, name, kind, x, y, hp, damage, hit_speed, range_,
                 sight, speed, targets, air=False, splash=0.0, size=0.4, deploy=0.0,
                 decay=0.0, role=None, card=None, jumps=False, value=0.0):
        self.id = eid
        self.owner = owner
        self.card = card
        self.name = name
        self.kind = kind
        self.x, self.y = x, y
        self.hp = self.max_hp = hp
        self.damage = damage
        self.hit_speed = hit_speed
        self.range = range_
        self.sight = sight
        self.speed = speed
        self.targets = targets
        self.air = air
        self.splash = splash
        self.size = size
        self.cooldown = 0.0
        self.target = None
        self.deploy = deploy
        self.decay = decay
        self.role = role            # 'king' / 'left' / 'right' for towers
        self.active = role != "king"
        self.jumps = jumps
        self.value = value          # elixir worth of this single unit

    @property
    def is_building(self):
        return self.kind != "troop"

    @property
    def alive(self):
        return self.hp > 0

    def can_target(self, other):
        if self.targets == "buildings":
            return other.is_building
        if self.targets == "ground":
            return not other.air
        return True


@dataclass
class UnitView:
    id: int
    name: str
    card: Card
    x: float
    y: float
    hp: float
    max_hp: float
    air: bool
    kind: str
    targets: str
    deploying: bool
    target_id: int


@dataclass
class TowerView:
    role: str
    x: float
    y: float
    hp: float
    max_hp: float
    alive: bool
    active: bool


@dataclass
class Observation:
    player: int
    time: float
    elixir: float
    elixir_mult: float
    hand: list
    next_card: Card
    my_units: list
    enemy_units: list
    my_towers: dict
    enemy_towers: dict
    enemy_plays: list           # [(card, x, y)] opponent plays since last observation
    crowns: tuple               # (mine, theirs)
    overtime: bool

    def can_place(self, card, x, y):
        return legal_placement(card, x, y, self.enemy_towers)


@dataclass
class Action:
    card: str
    x: float
    y: float


def legal_placement(card, x, y, enemy_towers):
    """Placement rule in local coordinates."""
    if not (0.5 <= x <= WIDTH - 0.5 and 0.5 <= y <= HEIGHT - 0.5):
        return False
    if card.kind == "spell":
        return True
    if y <= RIVER_LO:
        return True
    # Pocket placement after taking a princess tower.
    if y <= 21.0:
        if x < WIDTH / 2 and not enemy_towers["left"].alive:
            return True
        if x >= WIDTH / 2 and not enemy_towers["right"].alive:
            return True
    return False


@dataclass
class PlayerState:
    deck: list
    level: float
    hand: list = field(default_factory=list)
    queue: list = field(default_factory=list)
    elixir: float = START_ELIXIR
    spent: float = 0.0
    leaked: float = 0.0
    plays: int = 0
    seen: list = field(default_factory=list)   # opponent plays not yet observed


@dataclass
class BattleResult:
    winner: int                 # 0, 1 or -1 for a draw
    crowns: tuple
    duration: float
    spent: tuple
    leaked: tuple
    tower_hp: tuple             # remaining tower hp fraction per player
    frames: list = None


class Battle:
    def __init__(self, decks, agents, levels=(11, 11), seed=None, record=False):
        self.rng = random.Random(seed)
        self.agents = agents
        self.t = 0.0
        self.next_id = 1
        self.entities = []
        self.spells = []            # [land_time, owner, card, x, y, mult]
        self.crowns = [0, 0]
        self.winner = None
        self.record = record
        self.frames = []
        self.players = []
        for p in (0, 1):
            deck = [CARDS[c] if isinstance(c, str) else c for c in decks[p]]
            if len(deck) != 8:
                raise ValueError("a deck needs exactly 8 cards")
            order = deck[:]
            self.rng.shuffle(order)
            self.players.append(PlayerState(deck=deck, level=levels[p],
                                             hand=order[:4], queue=order[4:]))
        self.towers = [{}, {}]
        for p in (0, 1):
            m = level_mult(levels[p])
            for role, (lx, ly) in TOWER_LAYOUT.items():
                st = TOWER_STATS["king" if role == "king" else "princess"]
                x, y = to_local(lx, ly, p)
                e = Entity(self._id(), p, f"{role} tower", "tower", x, y,
                           st["hp"] * m, st["damage"] * m, st["hit_speed"],
                           st["range"], st["range"], 0.0, "air_ground",
                           size=st["size"], role=role)
                self.towers[p][role] = e
                self.entities.append(e)
        for a, p in zip(agents, (0, 1)):
            if hasattr(a, "reset"):
                a.reset(p)

    @classmethod
    def from_observation(cls, obs, enemy_spells=(), my_spells=()):
        """Rebuild the visible state as a sandbox battle, seen from `obs.player`.

        In the sandbox the observing player is player 0 and nobody makes new
        plays, so it can be stepped forward to evaluate candidate actions.
        Spells are (land_time, owner, card, x, y, mult) in the observer's frame.
        """
        b = cls.__new__(cls)
        b.rng = random.Random(0)
        b.agents = None
        b.t = obs.time
        b.next_id = 1 << 30
        b.entities, b.spells = [], []
        b.crowns = list(obs.crowns)
        b.winner = None
        b.record, b.frames = False, []
        b.players = [PlayerState(deck=[], level=LEVEL_BASE, elixir=obs.elixir),
                     PlayerState(deck=[], level=LEVEL_BASE, elixir=0.0)]
        b.towers = [{}, {}]
        for owner, towers in ((0, obs.my_towers), (1, obs.enemy_towers)):
            for role, tv in towers.items():
                st = TOWER_STATS["king" if role == "king" else "princess"]
                m = tv.max_hp / st["hp"]
                e = Entity(b._id(), owner, f"{role} tower", "tower", tv.x, tv.y,
                           tv.max_hp, st["damage"] * m, st["hit_speed"], st["range"],
                           st["range"], 0.0, "air_ground", size=st["size"], role=role)
                e.hp = tv.hp if tv.alive else 0.0
                e.active = tv.active
                b.towers[owner][role] = e
                if tv.alive:            # destroyed towers stay as dead placeholders
                    b.entities.append(e)
        for owner, units in ((0, obs.my_units), (1, obs.enemy_units)):
            for u in units:
                c = u.card
                m = u.max_hp / c.hp
                e = Entity(u.id, owner, c.name, c.kind, u.x, u.y, u.max_hp, c.damage * m,
                           c.hit_speed, c.range, c.sight, c.speed, c.targets, air=c.air,
                           splash=c.splash, size=UNIT_SIZE[c.kind],
                           deploy=0.5 if u.deploying else 0.0,
                           decay=(u.max_hp / c.lifetime) if c.lifetime else 0.0,
                           card=c, jumps=c.jumps_river, value=c.cost / c.count)
                e.hp = u.hp
                b.entities.append(e)
        for spell in list(enemy_spells) + list(my_spells):
            if spell[0] > obs.time:
                b.spells.append(list(spell))
        return b

    def inject(self, p, card, x, y, mult=1.0):
        """Deploy `card` for player `p` at world (x, y) without elixir/hand checks."""
        if card.kind == "spell":
            self.spells.append([self.t + card.travel, p, card, x, y, mult])
        else:
            self._spawn(p, card, x, y, mult)

    # ------------------------------------------------------------------ helpers
    def _id(self):
        self.next_id += 1
        return self.next_id

    @property
    def overtime(self):
        return self.t >= REGULATION

    def elixir_mult(self):
        if self.t < REGULATION - 60:
            return 1.0
        if self.t < REGULATION + OVERTIME - 60:
            return 2.0
        return 3.0

    def observe(self, p):
        q = 1 - p

        def uview(e):
            x, y = to_local(e.x, e.y, p)
            return UnitView(e.id, e.name, e.card, x, y, e.hp, e.max_hp, e.air, e.kind,
                            e.targets, e.deploy > 0,
                            e.target.id if e.target is not None else -1)

        def tview(e):
            x, y = to_local(e.x, e.y, p)
            return TowerView(e.role, x, y, max(e.hp, 0.0), e.max_hp, e.alive, e.active)

        ps = self.players[p]
        seen, ps.seen = ps.seen, []
        units = [e for e in self.entities if e.kind != "tower"]
        return Observation(
            player=p, time=self.t, elixir=ps.elixir, elixir_mult=self.elixir_mult(),
            hand=list(ps.hand), next_card=ps.queue[0] if ps.queue else None,
            my_units=[uview(e) for e in units if e.owner == p],
            enemy_units=[uview(e) for e in units if e.owner == q],
            my_towers={r: tview(e) for r, e in self.towers[p].items()},
            enemy_towers={r: tview(e) for r, e in self.towers[q].items()},
            enemy_plays=seen, crowns=(self.crowns[p], self.crowns[q]),
            overtime=self.overtime)

    # ------------------------------------------------------------------ actions
    def play(self, p, action):
        ps = self.players[p]
        card = next((c for c in ps.hand if c.name == action.card), None)
        if card is None or ps.elixir < card.cost:
            return False
        enemy_towers = {r: e for r, e in self.towers[1 - p].items()}
        if not legal_placement(card, action.x, action.y,
                               {r: _Alive(e.alive) for r, e in enemy_towers.items()}):
            return False
        ps.elixir -= card.cost
        ps.spent += card.cost
        ps.plays += 1
        ps.hand.remove(card)
        if ps.queue:
            ps.hand.append(ps.queue.pop(0))
        ps.queue.append(card)
        self.players[1 - p].seen.append((card, action.x, HEIGHT - action.y))
        x, y = to_local(action.x, action.y, p)
        if self.record:
            self.frames.append({"play": [p, card.name, round(x, 1), round(y, 1),
                                         round(self.t, 1)]})
        m = level_mult(ps.level)
        if card.kind == "spell":
            self.spells.append([self.t + card.travel, p, card, x, y, m])
        else:
            self._spawn(p, card, x, y, m)
        return True

    def _spawn(self, p, card, x, y, m):
        n = card.count
        ring = 0.0 if n == 1 else (0.7 if n <= 5 else 1.3)
        for i in range(n):
            ang = 2 * math.pi * i / n
            ux = min(max(x + ring * math.cos(ang), 0.5), WIDTH - 0.5)
            uy = min(max(y + ring * math.sin(ang), 0.5), HEIGHT - 0.5)
            self.entities.append(Entity(
                self._id(), p, card.name, card.kind, ux, uy, card.hp * m,
                card.damage * m, card.hit_speed, card.range, card.sight, card.speed,
                card.targets, air=card.air, splash=card.splash,
                size=UNIT_SIZE[card.kind], deploy=1.0,
                decay=(card.hp * m / card.lifetime) if card.lifetime else 0.0,
                card=card, jumps=card.jumps_river, value=card.cost / n))

    # ------------------------------------------------------------------ simulation
    def run(self):
        while self.winner is None:
            self.step()
        return self.result()

    def step(self):
        tick = int(round(self.t / DT))
        if self.agents is not None and tick % int(round(AGENT_INTERVAL / DT)) == 0:
            for p in (0, 1):
                action = self.agents[p].act(self.observe(p))
                if action is not None:
                    self.play(p, action)

        mult = self.elixir_mult()
        for ps in self.players:
            gain = DT / ELIXIR_PERIOD * mult
            room = MAX_ELIXIR - ps.elixir
            if gain > room:
                ps.leaked += gain - room
                gain = max(room, 0.0)
            ps.elixir += gain

        self._resolve_spells()
        for e in self.entities:
            if e.alive:
                self._update(e)
        self._cleanup()

        if self.record and tick % 3 == 0:
            self.frames.append(self._frame())
        self.t += DT
        self._check_end()

    def _resolve_spells(self):
        remaining = []
        for s in self.spells:
            land, p, card, x, y, m = s
            if land > self.t:
                remaining.append(s)
                continue
            dmg = card.damage * m
            for e in self.entities:
                if e.owner == p or not e.alive:
                    continue
                if math.hypot(e.x - x, e.y - y) <= card.radius + e.size * 0.5:
                    self._damage(e, dmg * card.tower_pct if e.kind == "tower" else dmg)
            if self.record:
                self.frames.append({"spell": [card.name, round(x, 2), round(y, 2),
                                              card.radius, p]})
        self.spells = remaining

    def _damage(self, e, dmg):
        e.hp -= dmg
        if e.kind == "tower" and e.role == "king":
            e.active = True

    def _in_range(self, e, t):
        return math.hypot(t.x - e.x, t.y - e.y) - t.size - e.size <= e.range

    def _nearest(self, e, radius, buildings_only=False):
        best, best_d = None, radius
        for o in self.entities:
            if o.owner == e.owner or not o.alive or not e.can_target(o):
                continue
            if buildings_only and not o.is_building:
                continue
            d = math.hypot(o.x - e.x, o.y - e.y) - o.size
            if d <= best_d:
                best, best_d = o, d
        return best

    def _update(self, e):
        if e.cooldown > 0:
            e.cooldown -= DT
        if e.deploy > 0:
            e.deploy -= DT
            return
        if e.decay:
            e.hp -= e.decay * DT
            if e.hp <= 0:
                return
        if e.kind == "tower" and not e.active:
            return

        t = e.target
        if t is not None and (not t.alive or not self._in_range(e, t)):
            t = None
        if t is None:
            if e.speed > 0:
                t = self._nearest(e, e.sight)
            else:
                t = self._nearest(e, e.range + 0.5)
                if t is not None and not self._in_range(e, t):
                    t = None
        e.target = t

        if t is not None and self._in_range(e, t):
            if e.cooldown <= 0:
                self._attack(e, t)
                e.cooldown = e.hit_speed
            return
        if e.speed <= 0:
            return
        dest = t if t is not None else self._default_dest(e)
        if dest is None:
            return
        self._move(e, dest.x, dest.y)

    def _default_dest(self, e):
        best, best_d = None, 1e9
        for tw in self.towers[1 - e.owner].values():
            if tw.alive:
                d = math.hypot(tw.x - e.x, tw.y - e.y)
                if d < best_d:
                    best, best_d = tw, d
        return best

    def _move(self, e, tx, ty):
        wx, wy = tx, ty
        if not e.air and not e.jumps:
            mine_below = e.y < RIVER_Y
            if mine_below != (ty < RIVER_Y):
                bx = min(BRIDGES, key=lambda b: abs(e.x - b) + abs(tx - b))
                if abs(e.x - bx) > 0.3:
                    wx, wy = bx, (RIVER_LO if mine_below else RIVER_HI)
                else:
                    wx, wy = bx, (RIVER_HI + 0.2 if mine_below else RIVER_LO - 0.2)
        dx, dy = wx - e.x, wy - e.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        step = min(e.speed * DT, d)
        e.x += dx / d * step
        e.y += dy / d * step

    def _attack(self, e, t):
        if e.splash > 0:
            for o in self.entities:
                if o.owner != e.owner and o.alive and e.can_target(o) and \
                        math.hypot(o.x - t.x, o.y - t.y) <= e.splash + o.size * 0.5:
                    self._damage(o, e.damage)
        else:
            self._damage(t, e.damage)

    def _cleanup(self):
        survivors = []
        for e in self.entities:
            if e.alive:
                survivors.append(e)
                continue
            if e.kind == "tower":
                if e.role == "king":
                    self.crowns[1 - e.owner] = 3
                    self.winner = 1 - e.owner
                else:
                    self.crowns[1 - e.owner] += 1
                    self.towers[e.owner]["king"].active = True
        self.entities = survivors

    def _check_end(self):
        if self.winner is not None:
            return
        if self.t >= REGULATION and self.crowns[0] != self.crowns[1]:
            self.winner = 0 if self.crowns[0] > self.crowns[1] else 1
        elif self.t >= REGULATION + OVERTIME:
            # Tiebreaker: the player whose weakest tower has more hp wins.
            lows = [min(tw.hp for tw in self.towers[p].values() if tw.alive) for p in (0, 1)]
            if abs(lows[0] - lows[1]) < 1e-6:
                self.winner = -1
            else:
                self.winner = 0 if lows[0] > lows[1] else 1

    def tower_fraction(self, p):
        tw = self.towers[p].values()
        return sum(max(t.hp, 0) for t in tw) / sum(t.max_hp for t in tw)

    def result(self):
        return BattleResult(
            winner=self.winner, crowns=tuple(self.crowns), duration=self.t,
            spent=tuple(ps.spent for ps in self.players),
            leaked=tuple(ps.leaked for ps in self.players),
            tower_hp=(self.tower_fraction(0), self.tower_fraction(1)),
            frames=self.frames if self.record else None)

    def _frame(self):
        return {
            "t": round(self.t, 1),
            "elixir": [round(ps.elixir, 2) for ps in self.players],
            "crowns": list(self.crowns),
            "e": [[e.name, e.owner, round(e.x, 2), round(e.y, 2),
                   round(max(e.hp, 0) / e.max_hp, 3), int(e.air), e.kind, e.id]
                  for e in self.entities],
        }


class _Alive:
    __slots__ = ("alive",)

    def __init__(self, alive):
        self.alive = alive
