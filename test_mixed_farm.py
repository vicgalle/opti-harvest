import unittest
from pathlib import Path

from island import read_grid
from island_route import check_walk, read_walk
from mixed_farm import check_farm

HERE = Path(__file__).parent / 'examples' / 'mixed-farm'


class MixedFarmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terrain = read_grid(HERE / 'terrain.txt')
        cls.layout = read_grid(HERE / 'farm.txt')

    def test_million_gold_build(self):
        board, h, f, crops, sprinklers = check_farm(self.terrain, self.layout)
        self.assertEqual((len(h), len(f), board.pots(f)), (1051, 60, 42))
        field = {(x, y) for x in range(52, 77) for y in range(13, 33)}
        self.assertEqual(crops | sprinklers, field)
        self.assertEqual((len(crops), len(sprinklers)), (480, 20))
        self.assertTrue(field.isdisjoint(board.floor))
        walk = read_walk(board.start, (HERE / 'harvest-walk.txt').read_text())
        check_walk(board, h, f, walk)
        self.assertEqual(len(walk)-1, 1320)

    def test_a_missing_sprinkler_leaves_dry_crops(self):
        rows = self.layout.copy()
        rows[15] = rows[15].replace('@', 'C', 1)
        with self.assertRaisesRegex(ValueError, 'sprinkler'):
            check_farm(self.terrain, rows)


if __name__ == '__main__':
    unittest.main()
