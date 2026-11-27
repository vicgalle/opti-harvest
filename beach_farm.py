"""Verify or optimize an enclosed sprinkler field and side-only apiary on the Beach Farm."""
import argparse
from itertools import groupby, product
from pathlib import Path

from ortools.sat.python import cp_model

from apiary import AROUND, STEPS, neighbors
from island import Island, connect_paths, read_grid, supports
from island_route import DIRECTIONS, check_walk, harvest_walk, read_walk


def distance(p, q):
    return abs(p[0] - q[0]) + abs(p[1] - q[1])


def replace(rows, changes):
    grid = [list(row) for row in rows]
    for (x, y), tile in changes.items():
        grid[y][x] = tile
    return [''.join(row) for row in grid]


class BeachFarm:
    def __init__(self, rows, *, standard=False):
        self.land = Island(rows, side_only=True)
        self.bed = self.land.beds
        self.wall = {n for p in self.bed for n in neighbors(p, AROUND)} - self.bed
        if not self.bed or self.wall - self.land.build:
            raise ValueError('the field needs a buildable border')
        # The map file starts at in-game (16, 41). The square part of the bed starts at (25, 50).
        if standard:
            # Eight ordinary iridium sprinklers in the 20x10 core. A basic sprinkler on
            # the lower tile of the two-tile extension waters its northern neighbor.
            self.irrigation = dict.fromkeys(product([11, 16, 21, 26], [11, 16]), (2, 'R'))
            self.irrigation[(8, 15)] = (1, 'b')
        else:
            self.irrigation = dict.fromkeys(product([11, 18, 25], [11, 16]), (3, '@'))
        self.sprinklers = set(self.irrigation)
        self.scarecrows = {(8, 13), (22, 8), (22, 19)}
        self.gate = (19, 8)
        self.posts = {(18, 8), (20, 8)}
        self.porch = (19, 7)
        self.fixed = (dict.fromkeys(self.scarecrows, 'K') | dict.fromkeys(self.posts, 'I') |
                      {self.gate: 'G'} | {p: symbol for p, (_, symbol) in self.irrigation.items()})
        if self.sprinklers - self.bed or (self.scarecrows | self.posts | {self.gate}) - self.wall:
            raise ValueError('field geometry does not match the Beach Farm map')
        closed = replace(rows, dict.fromkeys(self.bed | self.wall, 'X'))
        self.exterior = Island(closed, side_only=True)
        self.outside = self.exterior.flood(self.land.start, self.exterior.floor)

    def grid(self, houses, roses):
        changes = (dict.fromkeys(self.bed, 'C') | dict.fromkeys(self.wall, 'I') |
                   self.fixed | dict.fromkeys(houses, 'H') | dict.fromkeys(roses, 'F'))
        return replace(self.land.rows, changes)

    def verify(self, rows):
        if list(map(len, rows)) != list(map(len, self.land.rows)):
            raise ValueError('layout dimensions differ from the terrain')
        groups = {}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                groups.setdefault(ch, set()).add((x, y))
        houses, roses = groups.get('H', set()), groups.get('F', set())
        if roses - self.bed or houses - self.land.build or houses & self.bed:
            raise ValueError('illegal house or flower placement')
        for p, ch in self.fixed.items():
            if rows[p[1]][p[0]] != ch:
                raise ValueError(f'missing {ch} at {p}')
        if self.grid(houses, roses) != rows:
            raise ValueError('unexpected tile or gap in the field enclosure')
        crops = groups.get('C', set())
        for x, y in crops | roses:
            if not any((abs(x-a) + abs(y-b) <= 1 if symbol == 'b' else
                        max(abs(x-a), abs(y-b)) <= radius)
                       for (a, b), (radius, symbol) in self.irrigation.items()):
                raise ValueError(f'unwatered plant at {(x, y)}')
            if not any((x-a)**2 + (y-b)**2 <= 64 for a, b in self.scarecrows):
                raise ValueError(f'plant outside scarecrow coverage at {(x, y)}')
        # Check the open and closed gate as two physical states, independent of search constraints.
        walkable = groups.get('.', set()) | self.land.entries
        closed = self.land.flood(self.land.start, walkable)
        if self.porch not in closed:
            raise ValueError('cannot reach the gate')
        if any(closed.intersection(neighbors(p, AROUND)) for p in roses):
            raise ValueError('a flower can be picked from outside')
        opened = self.land.flood(self.land.start, walkable | crops | roses | {self.gate})
        if (crops | roses) - opened:
            raise ValueError('cannot reach every plant with the gate open')
        for h in houses:
            if not any(distance(h, f) <= 5 for f in roses):
                raise ValueError(f'no flower in range of house at {h}')
            if not closed.intersection(neighbors(h, STEPS)):
                raise ValueError(f'no closed-gate side pickup for house at {h}')
        return houses, roses, crops

    def stage(self, rows, order, count):
        houses, roses, _ = self.verify(rows)
        if len(order) != len(roses) or set(order) != roses or not 1 <= count <= len(order):
            raise ValueError('the planting order must list every flower once, and the stage must exist')
        planted = set(order[:count])
        active = {h for h in houses if any(distance(h, p) <= 5 for p in planted)}
        return self.grid(active, planted)

    def route_board(self, houses):
        # Ring houses are valid pickup targets. Other ring tiles and the entire bed are solid.
        walls = self.bed | (self.wall - houses)
        return Island(replace(self.land.rows, dict.fromkeys(walls, 'X')), side_only=True)

    def coverage(self):
        possible = ((self.outside | self.wall) & self.land.build) - self.fixed.keys() - {self.porch}
        spans = {f: {h for h in possible if distance(f, h) <= 5} for f in self.bed - self.sprinklers}
        # Replacing a dominated flower site by a better one leaves the same walkable crop bed.
        return {p: v for p, v in spans.items() if v and not any(
            v < w or (v == w and q < p) for q, w in spans.items())}

    def placement_model(self, coverage, budget):
        possible = set().union(*coverage.values())
        model = cp_model.CpModel()
        roses = {f: model.new_bool_var('rose') for f in sorted(coverage)}
        houses = {h: model.new_bool_var('house') for h in sorted(possible)}
        model.add(sum(roses.values()) <= budget)
        # Count each chosen flower's potential houses. Overlapping blooms only loosen this cap.
        model.add(sum(houses.values()) <= sum(len(coverage[p])*v for p, v in roses.items()))
        for h, placed in houses.items():
            supports(model, placed, (roses[p] for p, span in coverage.items() if h in span))
        patch = possible & self.exterior.floor
        reachable = connect_paths(model, self.exterior, patch, set(), {p: ~houses[p] for p in patch})
        supports(model, True, [reachable[self.porch]])
        for h, var in houses.items():
            supports(model, var, (reachable[n] for n in neighbors(h, STEPS) if n in reachable))
        model.maximize(sum(houses.values()))
        return model, houses, roses

    def optimize(self, budget, seconds, workers, *, initial=None):
        model, houses, roses = self.placement_model(self.coverage(), budget)
        if initial:
            old_h, old_f, _ = self.verify(initial)
            for p, var in houses.items():
                model.add_hint(var, int(p in old_h))
            for p, var in roses.items():
                model.add_hint(var, int(p in old_f))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = workers
        solver.parameters.max_time_in_seconds = seconds
        status = solver.solve(model)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            raise RuntimeError(f'search returned {solver.status_name(status)}')
        rows = self.grid({p for p, v in houses.items() if solver.value(v)},
                         {p for p, v in roses.items() if solver.value(v)})
        self.verify(rows)
        return rows, int(solver.best_objective_bound)


def read_order(path):
    # The build guide and this file use in-game coordinates. The terrain is a local window.
    return [(int(x) - 16, int(y) - 41) for x, y in
            (line.split() for line in Path(path).read_text().splitlines() if line.strip())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('terrain')
    parser.add_argument('layout', help='verified build, or output file when optimizing')
    parser.add_argument('--flowers', type=int, help='optimize with at most this many flowers')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--hint', help='start the optimizer with a verified build')
    path = parser.add_mutually_exclusive_group()
    path.add_argument('--walk', help='check a saved side-only round trip')
    path.add_argument('--save-walk', help='find and save a side-only round trip')
    parser.add_argument('--stage', type=int, help='build only the first N flowers in planting-order.txt')
    parser.add_argument('--standard', action='store_true',
                        help='use eight ordinary iridium sprinklers and one basic sprinkler')
    parser.add_argument('--print-grid', action='store_true', help='show the tiles to place')
    args = parser.parse_args()
    if args.stage is not None and args.flowers is not None:
        parser.error('choose either a published stage or an optimization search')
    terrain = read_grid(args.terrain)
    farm = BeachFarm(terrain, standard=args.standard and args.flowers is not None)
    if args.flowers is None:
        rows = read_grid(args.layout)
        if any('R' in row or 'b' in row for row in rows):
            farm = BeachFarm(terrain, standard=True)
    else:
        if Path(args.layout).resolve() == Path(args.terrain).resolve():
            parser.error('use a separate output file for the optimized layout')
        if args.flowers < 1 or args.seconds <= 0 or args.workers < 1:
            parser.error('the flower budget, time limit and worker count must be positive')
        rows, upper = farm.optimize(args.flowers, args.seconds, args.workers,
                                    initial=read_grid(args.hint) if args.hint else None)
        Path(args.layout).write_text('\n'.join(rows) + '\n')
        print(f'CP-SAT upper bound {upper} houses')
    if args.stage is not None:
        rows = farm.stage(rows, read_order(Path(args.layout).with_name('planting-order.txt')), args.stage)
    if args.standard and args.flowers is None:
        h, f, _ = farm.verify(rows)
        farm = BeachFarm(terrain, standard=True)
        if f & farm.sprinklers:
            parser.error('a flower in this stage occupies a standard sprinkler site')
        rows = farm.grid(h, f)
    h, f, crops = farm.verify(rows)
    if args.print_grid:
        print('\n'.join(rows))
    print(f'{len(h)} side-only bee houses, {len(f)} protected flowers and {len(crops)} irrigated crops')
    if args.walk or args.save_walk:
        board = farm.route_board(h)
        if args.walk:
            walk = read_walk(board.start, Path(args.walk).read_text())
        else:
            walk = harvest_walk(board, h, set(), args.seconds)
        check_walk(board, h, set(), walk)
        if args.save_walk:
            turns = (DIRECTIONS[(b[0]-a[0], b[1]-a[1])] for a, b in zip(walk, walk[1:]))
            tokens = [d + str(len(list(g))) for d, g in groupby(turns)]
            Path(args.save_walk).write_text(' '.join(tokens) + '\n')
        print(f'{len(walk)-1} exterior steps, returning to the starting tile')


if __name__ == '__main__':
    main()
