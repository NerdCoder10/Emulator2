"""Card definitions.

Stats are approximations of tournament-standard (level 11) Clash Royale cards.
Speeds are in tiles/second (slow 0.75, medium 1.0, fast 1.5, very fast 2.0).
"""
from dataclasses import dataclass

SLOW, MEDIUM, FAST, VERY_FAST = 0.75, 1.0, 1.5, 2.0


@dataclass(frozen=True)
class Card:
    name: str
    cost: int
    kind: str                    # 'troop' | 'building' | 'spell'
    hp: float = 0.0
    damage: float = 0.0
    hit_speed: float = 1.0
    speed: float = MEDIUM
    range: float = 1.0
    sight: float = 5.5
    targets: str = "ground"      # 'ground' | 'air_ground' | 'buildings'
    air: bool = False
    count: int = 1
    splash: float = 0.0          # splash radius of each hit
    radius: float = 0.0          # spell radius
    tower_pct: float = 0.3       # spell damage multiplier against crown towers
    travel: float = 0.0          # spell flight time before impact
    lifetime: float = 0.0        # building lifetime (decays to 0 over this time)
    jumps_river: bool = False
    roles: tuple = ()

    @property
    def dps(self) -> float:
        """Total damage per second of all units spawned by this card."""
        if self.kind == "spell" or self.hit_speed <= 0:
            return 0.0
        return self.damage / self.hit_speed * self.count

    @property
    def total_hp(self) -> float:
        return self.hp * self.count

    @property
    def can_hit_air(self) -> bool:
        return self.kind == "spell" or self.targets == "air_ground"

    @property
    def is_ranged(self) -> bool:
        return self.range >= 3.0

    @property
    def is_win_condition(self) -> bool:
        return "win" in self.roles


def _c(**kw) -> Card:
    return Card(**kw)


CARDS = {c.name: c for c in [
    # --- Troops -----------------------------------------------------------
    _c(name="Knight", cost=3, kind="troop", hp=1766, damage=202, hit_speed=1.2,
       speed=MEDIUM, range=1.2, roles=("mini_tank",)),
    _c(name="Archers", cost=3, kind="troop", hp=304, damage=107, hit_speed=0.9,
       speed=MEDIUM, range=5.0, targets="air_ground", count=2, roles=("air_def",)),
    _c(name="Giant", cost=5, kind="troop", hp=4091, damage=254, hit_speed=1.5,
       speed=SLOW, range=1.2, sight=7.5, targets="buildings", roles=("win", "tank")),
    _c(name="Musketeer", cost=4, kind="troop", hp=720, damage=217, hit_speed=1.0,
       speed=MEDIUM, range=6.0, targets="air_ground", roles=("air_def", "dps")),
    _c(name="Mini P.E.K.K.A", cost=4, kind="troop", hp=1361, damage=720, hit_speed=1.6,
       speed=FAST, range=0.8, roles=("dps",)),
    _c(name="Valkyrie", cost=4, kind="troop", hp=1907, damage=267, hit_speed=1.5,
       speed=MEDIUM, range=1.2, splash=2.0, roles=("splash", "mini_tank")),
    _c(name="Baby Dragon", cost=4, kind="troop", hp=1152, damage=161, hit_speed=1.5,
       speed=FAST, range=3.5, targets="air_ground", air=True, splash=1.5,
       roles=("splash", "air_def")),
    _c(name="Hog Rider", cost=4, kind="troop", hp=1697, damage=318, hit_speed=1.6,
       speed=VERY_FAST, range=0.8, sight=9.5, targets="buildings", jumps_river=True,
       roles=("win",)),
    _c(name="Skeleton Army", cost=3, kind="troop", hp=81, damage=81, hit_speed=1.0,
       speed=FAST, range=0.5, count=15, roles=("swarm", "dps")),
    _c(name="Skeletons", cost=1, kind="troop", hp=81, damage=81, hit_speed=1.0,
       speed=FAST, range=0.5, count=3, roles=("swarm", "cycle")),
    _c(name="Minions", cost=3, kind="troop", hp=230, damage=107, hit_speed=1.0,
       speed=FAST, range=2.0, targets="air_ground", air=True, count=3,
       roles=("swarm", "air_def")),
    _c(name="Spear Goblins", cost=2, kind="troop", hp=133, damage=81, hit_speed=1.7,
       speed=VERY_FAST, range=5.0, targets="air_ground", count=3,
       roles=("swarm", "air_def", "cycle")),
    _c(name="Barbarians", cost=5, kind="troop", hp=670, damage=192, hit_speed=1.3,
       speed=MEDIUM, range=0.7, count=5, roles=("swarm", "dps")),
    _c(name="Wizard", cost=5, kind="troop", hp=720, damage=281, hit_speed=1.4,
       speed=MEDIUM, range=5.5, targets="air_ground", splash=1.5,
       roles=("splash", "air_def")),
    _c(name="P.E.K.K.A", cost=7, kind="troop", hp=3760, damage=816, hit_speed=1.8,
       speed=SLOW, range=1.2, roles=("tank", "dps")),
    _c(name="Balloon", cost=5, kind="troop", hp=1679, damage=640, hit_speed=2.0,
       speed=MEDIUM, range=0.5, sight=7.5, targets="buildings", air=True,
       roles=("win",)),
    _c(name="Ice Golem", cost=2, kind="troop", hp=1197, damage=84, hit_speed=2.5,
       speed=SLOW, range=0.8, sight=7.0, targets="buildings", roles=("mini_tank", "cycle")),
    # --- Buildings ---------------------------------------------------------
    _c(name="Cannon", cost=3, kind="building", hp=824, damage=212, hit_speed=0.9,
       speed=0.0, range=5.5, lifetime=30.0, roles=("building",)),
    _c(name="Tesla", cost=4, kind="building", hp=1152, damage=230, hit_speed=1.1,
       speed=0.0, range=5.5, targets="air_ground", lifetime=30.0, roles=("building",)),
    # --- Spells ------------------------------------------------------------
    _c(name="Arrows", cost=3, kind="spell", damage=366, radius=4.0, travel=0.9,
       roles=("spell", "small_spell")),
    _c(name="Zap", cost=2, kind="spell", damage=192, radius=2.5, travel=0.0,
       roles=("spell", "small_spell")),
    _c(name="Fireball", cost=4, kind="spell", damage=689, radius=2.5, travel=1.0,
       roles=("spell", "big_spell")),
    _c(name="Rocket", cost=6, kind="spell", damage=1484, radius=2.0, travel=1.8,
       tower_pct=0.25, roles=("spell", "big_spell")),
]}


DECKS = {
    "giant_beatdown": ["Giant", "Musketeer", "Mini P.E.K.K.A", "Minions",
                       "Knight", "Skeletons", "Arrows", "Fireball"],
    "hog_cycle": ["Hog Rider", "Musketeer", "Cannon", "Skeletons",
                  "Ice Golem", "Spear Goblins", "Fireball", "Zap"],
    "balloon": ["Balloon", "Baby Dragon", "Valkyrie", "Minions",
                "Ice Golem", "Tesla", "Arrows", "Fireball"],
    "pekka_control": ["P.E.K.K.A", "Wizard", "Mini P.E.K.K.A", "Archers",
                      "Skeleton Army", "Knight", "Zap", "Fireball"],
    "starter": ["Knight", "Archers", "Giant", "Musketeer",
                "Minions", "Barbarians", "Arrows", "Fireball"],
    "hog_valk": ["Hog Rider", "Valkyrie", "Musketeer", "Tesla",
                 "Skeletons", "Minions", "Arrows", "Fireball"],
}


def deck_cards(names):
    return [CARDS[n] for n in names]
