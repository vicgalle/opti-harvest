import unittest

from closed_walk import check_walk, shortest_closed_walk
from greenhouse import EXAMPLES, PLANS, SCYTHE, WALKS, Greenhouse, plan
from island_route import read_walk

SMALL_BED = ['XXXXXXXXX',
             'X.......X',
             'X.SSSSS.X',
             'X.SSSSS.X',
             'X.SSSSS.X',
             'X.SSSSS.X',
             'X.......X',
             'XXXXEXXXX']
# A bed against two walls, with the best counts from a brute-force search over every plan.
WALLED_BED = ['XXXXXXX', 'XSSSS.X', 'XSSSS.X', 'XSSSS.X', 'XSSSS.X', 'XSSSS.X', 'X.....X', 'XXXEXXX']
WALLED_BEST = {'mouse': 16, 'side': 15, 'scythe': 18}


class GreenhouseTests(unittest.TestCase):
    def test_saved_plans_hold_their_claimed_crops(self):
        for name, (reach, count, sprinkler) in PLANS.items():
            hops, fruit, sprinklers, ground = Greenhouse(reach=reach).verify(plan(name))
            self.assertEqual(len(hops), count, name)
            self.assertEqual(set(sprinklers.values()), {3 if sprinkler == '@' else 2} if sprinkler else set(), name)
            self.assertTrue(fruit <= ground, name)

    def test_counting_bound_is_93_and_the_plan_fills_the_bed(self):
        house = Greenhouse()
        self.assertEqual(len(house.soil), 120)
        self.assertEqual(len(house.inner), 80)
        # Trellises <= 120 - w and <= 40 + 2w for w open soil tiles.
        self.assertEqual(max(min(120 - w, 40 + 2 * w) for w in range(121)), 93)
        hops, fruit, _, _ = house.verify(plan('93-hops'))
        self.assertEqual((len(hops), len(fruit)), (93, 27))

    def test_saved_walks_harvest_every_trellis(self):
        for name, (reach, steps) in WALKS.items():
            house = Greenhouse(reach=reach)
            hops, fruit, _, ground = house.verify(plan(name))
            walk = read_walk(house.board.start, (EXAMPLES / (name + '-walk.txt')).read_text())
            check_walk(house.board.start, ground, house.pickups(hops, fruit), walk)
            self.assertEqual(len(walk) - 1, steps, name)

    def test_reach_rules_are_enforced(self):
        rows = plan('93-hops')
        with self.assertRaisesRegex(ValueError, 'no reachable standing tile'):
            Greenhouse(reach='side').verify(rows)
        with self.assertRaisesRegex(ValueError, 'no reachable standing tile'):
            Greenhouse().verify([row.replace('A', 'T') for row in rows])
        dry = [row.replace('@', '.') if y < 13 else row for y, row in enumerate(plan('92-hops-sprinklers'))]
        with self.assertRaisesRegex(ValueError, 'unwatered'):
            Greenhouse().verify(dry)

    def test_small_bed_matches_the_open_rectangle_formula(self):
        house = Greenhouse(SMALL_BED)
        rows, bound = house.solve(seconds=20, workers=1)
        hops, fruit, _, ground = house.verify(rows)
        # 5 by 4 bed: 20 - ceil(3 * 2 / 3) = 18
        self.assertEqual((len(hops), bound), (18, 18))
        walk, proven = shortest_closed_walk(house.board.start, ground, house.pickups(hops, fruit), 20, 1)
        self.assertTrue(proven)
        check_walk(house.board.start, ground, house.pickups(hops, fruit), walk)

    def test_walled_bed_matches_brute_force_for_every_reach(self):
        for reach, best in WALLED_BEST.items():
            house = Greenhouse(WALLED_BED, reach=reach)
            rows, bound = house.solve(seconds=30, workers=1, tidy=False)
            self.assertEqual((len(house.verify(rows)[0]), bound), (best, best), reach)

    def test_scythe_reaches_two_tiles_around_and_three_up(self):
        house = Greenhouse(reach='scythe')
        self.assertEqual(len(house.stands[9, 14]), 27)
        self.assertIn((9, 17), house.stands[9, 14])      # a plant three tiles above the farmer is hit
        self.assertNotIn((9, 11), house.stands[9, 14])   # a plant three tiles below is not
        self.assertNotIn((11, 17), house.stands[9, 14])  # nor one three up and two across

    def test_scythe_reach_matches_a_player_built_pot_shed(self):
        rows = plan('wiki-168-pots')
        tiles = {(x, y): c for y, row in enumerate(rows) for x, c in enumerate(row)}
        aisle = {p for p, c in tiles.items() if c in '.E'}

        def in_reach(x, y):
            return any((x - dx, y - dy) in aisle for dx, dy in SCYTHE)
        pots = [p for p, c in tiles.items() if c == 'P']
        lamps = [p for p, c in tiles.items() if c == 'L']
        self.assertEqual((len(pots), len(lamps)), (168, 3))
        self.assertTrue(all(in_reach(*p) for p in pots))
        self.assertFalse(any(in_reach(*p) for p in lamps))


if __name__ == '__main__':
    unittest.main()
