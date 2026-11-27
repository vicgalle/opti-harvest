import unittest
from pathlib import Path

from beach_farm import BeachFarm, read_grid, read_order, replace
from island_route import check_walk, read_walk


ROOT = Path(__file__).resolve().parent / 'examples' / 'beach-farm'


class BeachFarmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terrain = read_grid(ROOT / 'terrain.txt')
        cls.farm = BeachFarm(cls.terrain)
        cls.plan = read_grid(ROOT / 'build.txt')
        cls.order = read_order(ROOT / 'planting-order.txt')

    def test_build_grows_without_moving_a_house(self):
        previous = set()
        counts = []
        for k in range(1, len(self.order) + 1):
            rows = self.farm.stage(self.plan, self.order, k)
            if k <= 5:
                self.assertEqual(read_grid(ROOT / f'stage-{k}.txt'), rows)
            houses, flowers, crops = self.farm.verify(rows)
            self.assertTrue(previous <= houses)
            self.assertEqual(len(crops) + len(flowers), 196)
            previous = houses
            counts.append(len(houses))
        self.assertEqual(counts[:5], [28, 54, 71, 88, 101])

    def test_same_harvest_with_standard_sprinklers(self):
        rows = self.farm.stage(self.plan, self.order, 5)
        houses, flowers, _ = self.farm.verify(rows)
        standard = BeachFarm(self.terrain, standard=True)
        _, _, crops = standard.verify(standard.grid(houses, flowers))
        self.assertEqual(len(crops), 188)
        for farm in (self.farm, standard):
            board = farm.route_board(houses)
            walk = read_walk(board.start, (ROOT / 'harvest-walk.txt').read_text())
            check_walk(board, houses, set(), walk)
            self.assertEqual(len(walk)-1, 290)

    def test_courtyard_needs_a_complete_wall_and_reachable_gate(self):
        rows = self.farm.stage(self.plan, self.order, 5)
        with self.assertRaisesRegex(ValueError, 'gap'):
            self.farm.verify(replace(rows, {(29, 10): '.'}))
        houses, flowers, _ = self.farm.verify(rows)
        with self.assertRaisesRegex(ValueError, 'gate'):
            self.farm.verify(self.farm.grid(houses | {self.farm.porch}, flowers))

    def test_optimizer_respects_only_permitted_picks(self):
        # One flower in the northwest corner has a known small optimum.
        flower = self.order[0]
        coverage = self.farm.coverage()
        model, houses, _ = self.farm.placement_model({flower: coverage[flower]}, 1)
        from ortools.sat.python import cp_model
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.max_time_in_seconds = 5
        self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
        placed = {p for p, var in houses.items() if solver.value(var)}
        self.assertEqual(len(placed), 28)
        self.farm.verify(self.farm.grid(placed, {flower}))


if __name__ == '__main__':
    unittest.main()
