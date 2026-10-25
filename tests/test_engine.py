import unittest

from crsim.agents import IdleAgent, RandomAgent, SimpleAgent, StrategicAgent
from crsim.cards import CARDS, DECKS
from crsim.engine import Action, Battle, legal_placement
from crsim.ladder import arena_for, gate_for, run_ladder


class EngineTests(unittest.TestCase):
    def test_decks_are_valid(self):
        for name, deck in DECKS.items():
            self.assertEqual(len(deck), 8, name)
            self.assertEqual(len(set(deck)), 8, name)
            for c in deck:
                self.assertIn(c, CARDS)

    def test_idle_vs_idle_goes_to_tiebreak_draw(self):
        r = Battle([DECKS["starter"]] * 2, [IdleAgent(), IdleAgent()], seed=1).run()
        self.assertEqual(r.winner, -1)
        self.assertAlmostEqual(r.duration, 300.0, delta=0.2)
        self.assertGreater(r.leaked[0], 0)

    def test_strategic_three_crowns_idle(self):
        r = Battle([DECKS["giant_beatdown"], DECKS["starter"]],
                   [StrategicAgent(), IdleAgent()], seed=0).run()
        self.assertEqual(r.winner, 0)
        self.assertEqual(r.crowns, (3, 0))

    def test_deterministic_with_seed(self):
        def run():
            return Battle([DECKS["hog_cycle"], DECKS["balloon"]],
                          [StrategicAgent(), SimpleAgent(seed=3)], seed=7).run()
        a, b = run(), run()
        self.assertEqual((a.winner, a.crowns, a.duration), (b.winner, b.crowns, b.duration))

    def test_placement_rules(self):
        class T:
            def __init__(self, alive):
                self.alive = alive
        towers = {"left": T(True), "right": T(True), "king": T(True)}
        knight, fireball = CARDS["Knight"], CARDS["Fireball"]
        self.assertTrue(legal_placement(knight, 3.5, 14.0, towers))
        self.assertFalse(legal_placement(knight, 3.5, 20.0, towers))
        self.assertTrue(legal_placement(fireball, 3.5, 25.0, towers))
        towers["left"] = T(False)
        self.assertTrue(legal_placement(knight, 3.5, 20.0, towers))
        self.assertFalse(legal_placement(knight, 14.5, 20.0, towers))

    def test_play_cycles_card_and_spends_elixir(self):
        b = Battle([DECKS["starter"]] * 2, [IdleAgent(), IdleAgent()], seed=0)
        card = next(c for c in b.players[0].hand if c.kind != "spell")
        nxt = b.players[0].queue[0]
        self.assertTrue(b.play(0, Action(card.name, 9.0, 10.0)))
        self.assertAlmostEqual(b.players[0].elixir, 5 - card.cost)
        self.assertNotIn(card, b.players[0].hand)
        self.assertIn(nxt, b.players[0].hand)
        self.assertIs(b.players[0].queue[-1], card)
        # Not enough elixir / card not in hand.
        self.assertFalse(b.play(0, Action(card.name, 9.0, 10.0)))

    def test_player_one_sees_mirrored_world(self):
        b = Battle([DECKS["starter"]] * 2, [IdleAgent(), IdleAgent()], seed=0)
        obs = b.observe(1)
        self.assertLess(obs.my_towers["king"].y, 16)
        self.assertGreater(obs.enemy_towers["king"].y, 16)

    def test_random_agent_runs(self):
        r = Battle([DECKS["starter"]] * 2, [RandomAgent(seed=1), RandomAgent(seed=2)],
                   seed=2).run()
        self.assertIn(r.winner, (-1, 0, 1))


class LadderTests(unittest.TestCase):
    def test_gates_and_arenas(self):
        self.assertEqual(arena_for(0), "Goblin Stadium")
        self.assertEqual(arena_for(1050), "Spell Valley")
        self.assertEqual(gate_for(1050), 1000)
        self.assertEqual(gate_for(6200), 4600)

    def test_short_climb(self):
        rep = run_ladder(StrategicAgent, DECKS["pekka_control"], battles=10, plateau=0)
        self.assertEqual(rep.battles, 10)
        self.assertGreater(rep.peak, 0)


if __name__ == "__main__":
    unittest.main()
