"""Find side-harvestable mushroom groves where every log sees ten mature trees."""
import argparse
from collections import deque
from itertools import combinations, groupby, product
from pathlib import Path

from ortools.sat.python import cp_model

from apiary import AROUND, STEPS, neighbors
from island import Island, connect_paths, supports
from island_route import DIRECTIONS

EXAMPLES = Path(__file__).parent / 'examples' / 'mushroom-grove'
MAX_LOGS = {10: 3, 11: 5, 12: 6, 13: 7}


def verify(rows):
    """Independently check growth, quantity, and side access on the actual map."""
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError('expected a rectangular tile plan')
    if set(''.join(rows)) - set('.ETL') or sum(row.count('E') for row in rows) != 1:
        raise ValueError('use T, L, . and exactly one entrance E')
    board = Island([row.translate(str.maketrans('TL', '..')) for row in rows], side_only=True)
    trees = {p for p in board.floor if rows[p[1]][p[0]] == 'T'}
    logs = {p for p in board.floor if rows[p[1]][p[0]] == 'L'}
    reached = board.flood(board.start, board.floor - trees - logs)
    for tree in trees:
        if trees.intersection(neighbors(tree, AROUND)):
            raise ValueError(f'adjacent mature trees at {tree}')
    for x, y in logs:
        if sum(abs(x-a) <= 3 and abs(y-b) <= 3 for a, b in trees) < 10:
            raise ValueError(f'fewer than ten trees within range of log at {(x, y)}')
    for p in trees | logs:
        if not board.sides[p] & reached:
            raise ValueError(f'no reachable side pickup at {p}')
    return board, trees, logs


def shortest_cover_walk(board, ground, targets):
    """Breadth-first search over (standing tile, items already collected)."""
    bits = {p: 1 << i for i, p in enumerate(sorted(targets))}
    pickups = {p: sum(bits[q] for q in board.sides[p] & targets) for p in ground}
    start = board.start, pickups[board.start]
    goal = board.start, (1 << len(targets)) - 1
    previous = {start: None}
    queue = deque([start])
    while queue:
        state = queue.popleft()
        if state == goal:
            walk = []
            while state is not None:
                walk.append(state[0])
                state = previous[state]
            return walk[::-1]
        p, covered = state
        for q in sorted(ground & board.sides[p]):
            new = q, covered | pickups[q]
            if new not in previous:
                previous[new] = state
                queue.append(new)
    raise ValueError('no complete harvest walk')


def harvest_walk(board, trees, logs, include_tappers=False):
    ground = board.flood(board.start, board.floor - trees - logs)
    required = set(logs)
    while True:
        walk = shortest_cover_walk(board, ground, required)
        if not include_tappers:
            return walk
        visited = set(walk)
        missed = {p for p in trees if not board.sides[p] & visited}
        if not missed:
            return walk
        # A shortest walk for a subset is a lower bound for the full joint trip.
        required.update(missed)


def canonical(shape):
    """Identify equivalent log patterns under translation, rotation and reflection."""
    forms = []
    for swap, sx, sy in product((False, True), (-1, 1), (-1, 1)):
        points = [(sx*y, sy*x) if swap else (sx*x, sy*y) for x, y in shape]
        xmin, ymin = map(min, zip(*points))
        forms.append(tuple(sorted((x-xmin, y-ymin) for x, y in points)))
    return min(forms)


def overlap_capacity(dx, dy):
    # Partition the intersection of two 7x7 windows into blocks of at most 2x2.
    return (max(0, 8-dx)//2) * (max(0, 8-dy)//2)


def log_shapes(budget, count):
    shared = 20 - budget
    span = 1 + max(d for d in range(7) if overlap_capacity(d, 0) >= shared)
    seen = set()

    def extend(shape, candidates):
        if len(shape) == count:
            if min(x for x, y in shape) or min(y for x, y in shape):
                return
            occupied = set(shape)
            if any(occupied.issuperset(neighbors(p, STEPS)) for p in shape):
                return
            key = canonical(shape)
            if key not in seen:
                seen.add(key)
                yield key
            return
        for i, (x, y) in enumerate(candidates):
            if len(shape) + len(candidates) - i < count:
                break
            compatible = [q for q in candidates[i+1:]
                          if overlap_capacity(abs(x-q[0]), abs(y-q[1])) >= shared]
            yield from extend(shape + [(x, y)], compatible)

    yield from extend([], list(product(range(span), repeat=2)))


def place_trees(shape, budget):
    # Only trees in a log's window matter. One clear tile outside their union
    # gives exactly the same exterior access as an unlimited open field.
    logs = {(x+4, y+4) for x, y in shape}
    width = max(x for x, y in logs) + 5
    height = max(y for x, y in logs) + 5
    board = Island(['E' + '.' * (width-1)] + ['.' * width] * (height-1), side_only=True)
    windows = {p: {(p[0]+dx, p[1]+dy) for dx, dy in product(range(-3, 4), repeat=2)}
               for p in logs}
    sites = set.union(*windows.values()) - logs
    model = cp_model.CpModel()
    tree = {p: model.new_bool_var(f'tree{p}') for p in sorted(sites)}
    model.add(sum(tree.values()) <= budget)
    for x, y in board.floor:
        block = sites.intersection(((x, y), (x+1, y), (x, y+1), (x+1, y+1)))
        if len(block) > 1:
            model.add_at_most_one(tree[p] for p in block)
    for window in windows.values():
        model.add(sum(tree[p] for p in window & sites) >= 10)

    reachable = connect_paths(model, board, sites, logs, {p: ~v for p, v in tree.items()})
    for p in logs | sites:
        supports(model, tree.get(p, True), (reachable[q] for q in board.sides[p] if q in reachable))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    status = solver.solve(model)
    if status == cp_model.INFEASIBLE:
        return None
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        raise RuntimeError(f'incomplete solve: {solver.status_name(status)}')
    rows = [list(row) for row in board.rows]
    for x, y in logs:
        rows[y][x] = 'L'
    for (x, y), var in tree.items():
        if solver.value(var):
            rows[y][x] = 'T'
    rows = [''.join(row) for row in rows]
    verify(rows)
    return rows


def regular_grid_max():
    """Try every eligible log subset in the 4-by-4 tapped-oak reference grove."""
    board, trees, _ = verify((EXAMPLES / 'regular-grid.txt').read_text().splitlines())
    if trees != set(product(range(1, 8, 2), repeat=2)):
        raise ValueError('expected 16 regularly spaced mature trees')
    sites = sorted((x, y) for x, y in board.floor - trees
                   if sum(abs(x-a) <= 3 and abs(y-b) <= 3 for a, b in trees) >= 10)
    for count in range(len(sites), -1, -1):
        for group in combinations(sites, count):
            occupied = trees.union(group)
            reached = board.flood(board.start, board.floor - occupied)
            if all(board.sides[p] & reached for p in occupied):
                return count


def prove():
    for budget, count in MAX_LOGS.items():
        _, trees, logs = verify((EXAMPLES / f'{budget}-trees.txt').read_text().splitlines())
        if len(trees) != budget or len(logs) != count:
            raise ValueError('published plan does not attain the claimed bound')
        cases = 0
        for shape in log_shapes(budget, count + 1):
            cases += 1
            if place_trees(shape, budget) is not None:
                raise RuntimeError(f'found a counterexample for {budget} trees')
        print(f'{budget} trees: {count} logs attained; all {cases} shapes for one more ruled out')
    _, trees, logs = verify((EXAMPLES / '14-trees.txt').read_text().splitlines())
    if (len(trees), len(logs)) != (14, 8):
        raise ValueError('expected the eight-log witness')
    print('Eight full-yield logs need at least 14 mature trees; the published grove attains it.')
    print(f'Regular 4-by-4 tapped-oak grid: {regular_grid_max()} full-yield side-accessible logs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', type=Path, metavar='PLAN')
    group.add_argument('--find', type=int, nargs=2, metavar=('TREE_BUDGET', 'LOGS'))
    group.add_argument('--prove', action='store_true')
    parser.add_argument('--walk', choices=('logs', 'all'), help='shortest closed walk for logs or logs and tappers')
    args = parser.parse_args()
    if args.walk and not args.check:
        parser.error('--walk needs --check')
    if args.prove:
        prove()
    elif args.check:
        board, trees, logs = verify(args.check.read_text().splitlines())
        print(f'{len(trees)} tappable trees, {len(logs)} accessible logs, {5*len(logs)} mushrooms per full harvest')
        if args.walk:
            walk = harvest_walk(board, trees, logs, include_tappers=args.walk == 'all')
            turns = (DIRECTIONS[b[0]-a[0], b[1]-a[1]] for a, b in zip(walk, walk[1:]))
            print(f'{len(walk)-1} steps: ' + ' '.join(d + str(len(list(g))) for d, g in groupby(turns)))
    else:
        budget, count = args.find
        if not 10 <= budget < 20 or count < 1:
            parser.error('the shared-tree search needs 10–19 trees and a positive log count')
        for shape in log_shapes(budget, count):
            rows = place_trees(shape, budget)
            if rows is not None:
                print('\n'.join(rows))
                return
        print('No feasible grove for that budget and log count.')


if __name__ == '__main__':
    main()
