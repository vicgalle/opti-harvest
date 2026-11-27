import unittest
from pathlib import Path

from island import Island, read_grid
from island_route import check_walk, read_walk

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'ginger-island'


class IslandTests(unittest.TestCase):
    def test_builds_and_published_walk(self):
        board = Island(read_grid(EXAMPLE / 'terrain.txt'))
        for count, roses, pots, edge_beds in [(600, 29, 24, 0), (602, 31, 26, 5)]:
            h, f = board.decode(read_grid(EXAMPLE / f'{count}-houses.txt'))
            board.verify(h, f)
            self.assertEqual((len(h), len(f), board.pots(f), len(f & board.edge_beds)),
                             (count, roses, pots, edge_beds))
            if count == 600:
                walk = read_walk(board.start, (EXAMPLE / 'harvest-walk.txt').read_text())
                check_walk(board, h, f, walk)
                self.assertEqual(len(walk) - 1, 758)
                reached = board.flood(board.start, board.floor - h - f)
                self.assertEqual(sum(not (board.sides[p] & reached) for p in h), 154)

    def test_diagonal_beside_interactable(self):
        houses, flowers = {(2, 2)}, {(4, 1)}
        clear = Island(['E.XXX', 'X.XXS', 'XX.XX'])
        clear.verify(houses, flowers)
        awkward = Island(['E.XXX', 'X.IXS', 'XX.XX'])
        with self.assertRaisesRegex(ValueError, 'pickup'):
            awkward.verify(houses, flowers)

    def test_exposed_rose(self):
        board = Island(['E..', 'XXS'])
        with self.assertRaisesRegex(ValueError, 'exposed flower'):
            board.verify(set(), {(2, 1)})


if __name__ == '__main__':
    unittest.main()
