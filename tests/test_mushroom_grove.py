import unittest

from island_route import check_walk, read_walk
from mushroom_grove import EXAMPLES, harvest_walk, log_shapes, place_trees, regular_grid_max, verify


def plan(name):
    return (EXAMPLES / (name + '.txt')).read_text().splitlines()


class MushroomGroveTests(unittest.TestCase):
    def test_saved_walks_attain_both_shortest_lengths(self):
        board, trees, logs = verify(plan('14-trees'))
        self.assertEqual((len(trees), len(logs)), (14, 8))
        counts = sorted(sum(max(abs(x-a), abs(y-b)) <= 3 for a, b in trees) for x, y in logs)
        self.assertEqual(counts, [10] * 7 + [11])
        for all_items, filename, length in [(False, 'mushroom-walk', 40), (True, 'joint-walk', 44)]:
            targets = trees | logs if all_items else logs
            walk = read_walk(board.start, ' '.join(plan(filename)))
            check_walk(board, targets, (trees | logs) - targets, walk)
            self.assertEqual(len(walk), length + 1)
            self.assertEqual(len(harvest_walk(board, trees, logs, all_items)), len(walk))

    def test_starter_upgrade_keeps_every_placement(self):
        _, old_trees, old_logs = verify(plan('10-trees'))
        board, trees, logs = verify(plan('11-trees'))
        self.assertTrue(old_trees < trees and old_logs < logs)
        self.assertEqual((len(old_trees), len(old_logs), len(trees), len(logs)), (10, 3, 11, 5))
        self.assertEqual(len(harvest_walk(board, trees, logs, True)) - 1, 22)

    def test_thirteen_tree_upper_bound(self):
        shapes = list(log_shapes(13, 8))
        self.assertEqual(len(shapes), 5)
        self.assertTrue(all(place_trees(shape, 13) is None for shape in shapes))

    def test_regular_grid_has_six_slots_and_rejects_sealed_pocket(self):
        self.assertEqual(regular_grid_max(), 6)
        rows = [list(row.replace('L', '.')) for row in plan('regular-grid')]
        for i in (2, 3, 5, 6):
            rows[4][i] = rows[i][4] = 'L'
        with self.assertRaisesRegex(ValueError, 'side pickup'):
            verify([''.join(row) for row in rows])
