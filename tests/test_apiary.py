import itertools
import json
import unittest
from pathlib import Path

from apiary import Plot, check_layout, draw, seed_layout, solve


def brute_force(plot):
    """Try all placements on a tiny rectangle, using coordinate distances directly."""
    cells = [(x, y) for y in range(plot.height) for x in range(plot.width)]
    border = {p for p in cells if p[0] in (0, plot.width-1) or p[1] in (0, plot.height-1)}

    def distance(p, q):
        return abs(p[0] - q[0]) + abs(p[1] - q[1])

    def can_collect(p, q):
        if plot.collection == 4:
            return distance(p, q) == 1
        return max(abs(p[0] - q[0]), abs(p[1] - q[1])) == 1

    best = 0
    for tiles in itertools.product('HF.', repeat=len(cells)):
        hives = {p for p, t in zip(cells, tiles) if t == 'H'}
        if len(hives) <= best:
            continue
        blooms = {p for p, t in zip(cells, tiles) if t == 'F'}
        if plot.center_only and blooms != {plot.center}:
            continue
        if plot.max_flowers is not None and len(blooms) > plot.max_flowers:
            continue
        if not all(any(distance(h, f) <= 5 for f in blooms) for h in hives):
            continue
        ground = set(cells) - hives
        if plot.solid_flowers:
            ground -= blooms
        if plot.entrance is None:
            reached = ground & border
            from_outside = hives & border
        else:
            if plot.entrance not in ground - blooms:
                continue
            reached = {plot.entrance}
            from_outside = set()
        while True:
            more = {p for p in ground - reached if any(distance(p, q) == 1 for q in reached)}
            if not more:
                break
            reached |= more
        if all(any(can_collect(h, p) for p in reached) for h in hives - from_outside):
            best = len(hives)
    return best


class ApiaryTests(unittest.TestCase):
    def test_published_layouts(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'layouts.json'
        for result in json.loads(path.read_text()):
            with self.subTest(plot=result['plot']):
                check_layout(Plot(**result['plot']), result['rows'])
                tiles = ''.join(result['rows'])
                self.assertEqual(tiles.count('H'), result['houses'])
                self.assertEqual(tiles.count('F'), result['flowers'])
                self.assertEqual(result['houses'], result['upper_bound'])

    def test_against_enumeration(self):
        for collection, solid, gate, centered in itertools.product(
                (4, 8), (False, True), (None, (0, 1)), (False, True)):
            plot = Plot(3, 3, collection, gate, solid, centered, 1)
            with self.subTest(plot=plot):
                result = solve(plot, seconds=5, workers=1)
                self.assertEqual((result['houses'], result['upper_bound']), (brute_force(plot),) * 2)

    def test_unreachable_standing_tile(self):
        with self.assertRaisesRegex(ValueError, 'cannot collect'):
            check_layout(Plot(5, 5), ['HHHHH', 'HHHHH', 'HHFHH', 'HHHHH', 'HHHHH'])

    def test_flower_can_be_part_of_route(self):
        rows = ['HHH', '.FH', 'HHH']
        check_layout(Plot(3, 3, entrance=(0, 1)), rows)
        with self.assertRaisesRegex(ValueError, 'cannot collect'):
            check_layout(Plot(3, 3, entrance=(0, 1), solid_flowers=True), rows)

    def test_flower_range(self):
        check_layout(Plot(5, 2), ['F....', '....H'])
        with self.assertRaisesRegex(ValueError, 'no flower'):
            check_layout(Plot(5, 3), ['F....', '.....', '....H'])

    def test_stripes_attain_bound(self):
        for w, h in itertools.product(range(3, 13), repeat=2):
            plot = Plot(w, h)
            hives, blooms = seed_layout(plot)
            check_layout(plot, draw(plot, hives, blooms))
            self.assertEqual(len(hives), w*h - ((w-2)*(h-2) + 2)//3, (w, h))

    def test_thin_or_unplanted_plots(self):
        for plot, expected in ((Plot(1, 1), 0), (Plot(1, 12), 10),
                               (Plot(3, 3, max_flowers=0), 0)):
            result = solve(plot, seconds=5, workers=1)
            self.assertEqual((result['houses'], result['upper_bound']), (expected, expected))


if __name__ == '__main__':
    unittest.main()
