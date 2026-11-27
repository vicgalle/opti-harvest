"""Replay the harvest, check flowering/watering/shielding, and optionally optimize the fixed lap."""
import argparse
from collections import Counter
from pathlib import Path

WIDTH = 20
HEIGHT = 7
SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))
AROUND = [(x, y) for x in range(-1, 2) for y in range(-1, 2) if (x, y) != (0, 0)]


def neighbors(p, offsets):
    return {(p[0] + dx, p[1] + dy) for dx, dy in offsets}


def distance(p, q):
    return abs(p[0] - q[0]) + abs(p[1] - q[1])


def harvest_walk(copies):
    # Cross every upper lane, then harvest each module's remaining three sides on the return.
    moves = [((1, 0), WIDTH * copies - 1)]
    for i in range(copies):
        if i:
            moves.append(((-1, 0), 1))
        moves += [((0, 1), 4), ((-1, 0), WIDTH - 1), ((0, -1), 4)]
    walk = [(0, 1)]
    for (dx, dy), length in moves:
        for _ in range(length):
            x, y = walk[-1]
            walk.append((x + dx, y + dy))
    return walk


def verify(rows, copies):
    if len(rows) != HEIGHT or any(len(row) != WIDTH for row in rows):
        raise ValueError('expected a 20 by 7 module')
    tiles = {(x, y): char for y, row in enumerate(rows) for x, char in enumerate(row * copies)}
    counts = Counter(tiles.values())
    if set(counts) - set('HFSC.'):
        raise ValueError('unexpected grid symbol')
    positions = {ch: {p for p, char in tiles.items() if char == ch} for ch in 'HFSC.'}
    walk = harvest_walk(copies)
    if walk[-1] != walk[0] or any(tiles.get(p) != '.' for p in walk):
        raise ValueError('harvest walk must stay on clear ground and return to its entrance')
    for p in positions['F']:
        if any(tiles.get(q) not in ('H', 'F', 'S', 'C') for q in neighbors(p, AROUND)):
            raise ValueError(f'unshielded rose at {p}')
        if not neighbors(p, SIDES) & positions['S']:
            raise ValueError(f'unwatered rose at {p}')
        # Manhattan distance <= 8 is a conservative subset of ordinary scarecrow coverage.
        if not any(distance(p, q) <= 8 for q in positions['C']):
            raise ValueError(f'rose outside scarecrow coverage at {p}')
    collected = set().union(*(neighbors(p, SIDES) for p in walk))
    for p in positions['H']:
        if p not in collected or not any(distance(p, f) <= 5 for f in positions['F']):
            raise ValueError(f'uncollectible or uncovered house at {p}')
    if (counts['H'], counts['F'], counts['S'], counts['C']) != tuple(
        n * copies for n in (78, 4, 4, 2)
    ):
        raise ValueError('unexpected material or house count')
    if len(walk) - 1 != 48 * copies - 2:
        raise ValueError('unexpected walk length')
    return counts['H'], len(walk) - 1


def solve_module():
    """Allow any placements in the rectangle while harvesting exclusively from the fixed lap."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    grid = {(x, y) for y in range(HEIGHT) for x in range(WIDTH)}
    lap = set(harvest_walk(1))
    v = {ch: {p: model.new_bool_var(f'{ch}{p}') for p in sorted(grid)} for ch in 'HFSC.'}
    for p in grid:
        model.add_exactly_one(layer[p] for layer in v.values())
        if p in lap:
            model.add(v['.'][p] == 1)
        if not neighbors(p, SIDES) & lap:
            model.add(v['H'][p] == 0)
        model.add_bool_or([~v['H'][p]] + [v['F'][q] for q in grid if distance(p, q) <= 5])
        around = neighbors(p, AROUND)
        if not around <= grid:
            model.add(v['F'][p] == 0)
        for q in around & grid:
            model.add_at_most_one(v['F'][p], v['.'][q])
        model.add_bool_or([~v['F'][p]] + [v['S'][q] for q in neighbors(p, SIDES) & grid])
        model.add_bool_or([~v['F'][p]] + [v['C'][q] for q in grid if distance(p, q) <= 8])
    for ch, count in [('F', 4), ('S', 4), ('C', 2)]:
        model.add(sum(v[ch].values()) == count)
    model.maximize(sum(v['H'].values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    if solver.solve(model) != cp_model.OPTIMAL:
        raise RuntimeError('CP-SAT did not close the bound')
    rows = [''.join(next(ch for ch in v if solver.value(v[ch][x, y])) for x in range(WIDTH))
            for y in range(HEIGHT)]
    verified, _ = verify(rows, 1)
    if solver.best_objective_bound != verified:
        raise ValueError('upper bound differs from verified house count')
    print(f'CP-SAT proved {verified} houses optimal on the fixed lap.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copies', type=int, default=1, help='place copies side-by-side inside one plot')
    parser.add_argument('--solve', action='store_true', help='also rerun the fixed-lap CP-SAT model')
    args = parser.parse_args()
    if args.copies < 1:
        parser.error('--copies must be positive')
    module = Path(__file__).with_name('layout.txt').read_text().splitlines()
    houses, steps = verify(module, args.copies)
    print(f'Verified {houses} side pickups on a {WIDTH * args.copies} by {HEIGHT} plot in {steps} steps.')
    if args.solve:
        solve_module()
