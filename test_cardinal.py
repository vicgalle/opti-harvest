import unittest
from pathlib import Path

from island import Island, read_grid
from island_route import check_walk, read_walk

EXAMPLE = Path(__file__).parent / 'examples' / 'ginger-island'


class CardinalPickupTests(unittest.TestCase):
    def test_diagonal_stand_does_not_count(self):
        rows = ['E.XXX', 'X.XXS', 'XX.XX']
        houses, flowers = {(2, 2)}, {(4, 1)}
        Island(rows).verify(houses, flowers)
        with self.assertRaisesRegex(ValueError, 'pickup'):
            Island(rows, side_only=True).verify(houses, flowers)

    def test_side_only_route_must_visit_the_side(self):
        rows = ['E.XXX', '..XXS', 'X.XXX']
        houses, flowers = {(1, 1)}, {(4, 1)}
        board = Island(rows, side_only=True)
        board.verify(houses, flowers)
        with self.assertRaisesRegex(ValueError, 'pickup'):
            check_walk(board, houses, flowers, [board.start])
        check_walk(board, houses, flowers, [board.start, (1, 0), board.start])

    def test_published_side_only_walk(self):
        board = Island(read_grid(EXAMPLE / 'terrain.txt'), side_only=True)
        folder = EXAMPLE / 'side-only'
        houses, flowers = board.decode(read_grid(folder / '545-houses.txt'))
        board.verify(houses, flowers)
        self.assertEqual((len(houses), len(flowers), board.pots(flowers)), (545, 27, 24))
        self.assertFalse(flowers & board.edge_beds)
        walk = read_walk(board.start, (folder / 'harvest-walk.txt').read_text())
        check_walk(board, houses, flowers, walk)
        self.assertEqual(len(walk) - 1, 868)
        reached = set(walk)
        self.assertTrue(all(any(abs(x-a) + abs(y-b) == 1 for a, b in reached)
                            for x, y in houses))
