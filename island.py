"""Verify or improve a sheltered-flower layout on the Ginger Island terrain grid."""
import argparse
import math
import random
from collections import defaultdict, deque
from pathlib import Path

from ortools.sat.python import cp_model

from apiary import AROUND, BLOOM, STEPS, neighbors


def read_grid(path):
    return [r for r in Path(path).read_text().splitlines() if not r.startswith('#')]


class Island:
    def __init__(self, rows, *, side_only=False):
        self.rows = rows
        self.base = {(x, y): c for y, row in enumerate(rows) for x, c in enumerate(row)}
        if set(self.base.values()) - set('.PSEWXI '):
            raise ValueError('unexpected terrain symbol')
        self.floor = {p for p, c in self.base.items() if c in '.PSEW'}
        self.beds = {p for p in self.floor if self.base[p] in 'PS'}
        self.edge_beds = {p for p in self.beds if any(
            self.base.get(n, ' ') == ' ' for n in neighbors(p, AROUND))}
        self.build = {p for p in self.floor if self.base[p] in '.PS'}
        self.entries = {p for p in self.floor if self.base[p] == 'E'}
        self.start = min(self.entries, key=lambda p: (p[1], p[0]))
        self.sides = {p: self.floor.intersection(neighbors(p, STEPS)) for p in self.floor}
        self.around = {p: self.floor.intersection(neighbors(p, AROUND)) for p in self.floor}
        self.blooms = {p: self.beds.intersection(neighbors(p, BLOOM)) for p in self.build}
        if side_only:
            self.stands = {p: self.sides[p] for p in self.build}
        else:
            awkward = {p for p in self.floor if any(self.base.get(n) == 'I' for n in neighbors(p, AROUND))}
            self.stands = {p: self.sides[p] | (self.around[p] - awkward) for p in self.build}

    def decode(self, rows):
        if list(map(len, rows)) != list(map(len, self.rows)):
            raise ValueError('layout must match terrain dimensions')
        houses, flowers = set(), set()
        for p, terrain in self.base.items():
            x, y = p
            c = rows[y][x]
            if c == 'B' and p in self.build:
                houses.add(p)
            elif (c, terrain) in (('F', 'S'), ('f', 'P')):
                flowers.add(p)
            elif c != terrain:
                raise ValueError(f'invalid placement {c} at {p} on {terrain}')
        return houses, flowers

    def grid(self, houses, flowers):
        rows = [list(row) for row in self.rows]
        for x, y in houses:
            rows[y][x] = 'B'
        for x, y in flowers:
            rows[y][x] = 'F' if self.base[x, y] == 'S' else 'f'
        return [''.join(row) for row in rows]

    def flood(self, start, empty):
        reached = {start}
        queue = deque(reached)
        while queue:
            fresh = (self.sides[queue.popleft()] & empty) - reached
            reached.update(fresh)
            queue.extend(fresh)
        return reached

    def verify(self, houses, flowers):
        if houses - self.build or flowers - self.beds or houses & flowers:
            raise ValueError('illegal placement')
        empty = self.floor - houses - flowers
        reached = self.flood(self.start, empty)
        if self.entries - reached:
            raise ValueError('disconnected entrances')
        for p in flowers:
            if self.around[p] & empty:
                raise ValueError(f'exposed flower at {p}')
        for p in houses:
            if not self.blooms[p] & flowers:
                raise ValueError(f'no flower for {p}')
            if not self.stands[p] & reached:
                raise ValueError(f'no reachable controller-friendly pickup for {p}')

    def pots(self, flowers):
        return sum(self.base[p] == 'P' for p in flowers)


def connect_paths(model, board, patch, occupied, walk):
    """Contract each fixed open component to a node and root the walk at one entrance."""
    nodes = {p: p for p in patch}
    free = board.floor - patch - occupied
    while free:
        component = board.flood(next(iter(free)), free)
        node = min(component)
        nodes.update(dict.fromkeys(component, node))
        free -= component
    graph = defaultdict(set)
    for p in patch:
        for n in board.sides[p]:
            if n in nodes:
                graph[p].add(nodes[n])
                graph[nodes[n]].add(p)
    root = nodes[board.start]
    reachable = {n: model.new_bool_var(f'reach{n}') for n in set(nodes.values())}
    depth = {n: model.new_int_var(0, len(reachable), f'depth{n}') for n in reachable}
    model.add(depth[root] == 0)
    for e in board.entries:
        model.add(reachable[nodes[e]] == 1)
    for n, r in reachable.items():
        if n in patch:
            model.add_implication(r, walk[n])
        if n == root:
            continue
        parents = []
        for m in graph[n]:
            use = model.new_bool_var('parent')
            model.add_implication(use, reachable[m])
            model.add(depth[m] < depth[n]).only_enforce_if(use)
            parents.append(use)
        model.add_bool_or([~r, *parents])
    # Treat the root as a constant in the many distant, already served pickup clauses.
    return {p: True if n == root else reachable[n] for p, n in nodes.items()}


def supports(model, condition, options):
    options = list(options)
    if any(x is True for x in options):
        return
    if condition is not True:
        options.append(~condition)
    model.add_bool_or(options)


def improve_patch(board, houses, flowers, patch, pot_limit, flower_limit, args):
    patch &= board.build
    if not patch:
        return houses, flowers
    model = cp_model.CpModel()
    hive = {p: model.new_bool_var(f'B{p}') for p in sorted(patch)}
    rose = {p: model.new_bool_var(f'F{p}') for p in sorted(patch & board.beds)}
    walk = {p: model.new_bool_var(f'W{p}') for p in sorted(patch)}
    old_h, old_f = houses - patch, flowers - patch
    for p in patch:
        model.add_exactly_one([hive[p], walk[p]] + ([rose[p]] if p in rose else []))
        model.add_hint(hive[p], int(p in houses))
        model.add_hint(walk[p], int(p not in houses and p not in flowers))
        if p in rose:
            model.add_hint(rose[p], int(p in flowers))
    model.add(sum(rose.values()) <= flower_limit - len(old_f))
    pots = sum(v for p, v in rose.items() if board.base[p] == 'P')
    model.add(pots <= pot_limit - board.pots(old_f))
    reachable = connect_paths(model, board, patch, old_h | old_f, walk)
    for p in old_h | patch:
        h = hive.get(p, True)
        if not board.blooms[p] & old_f:
            supports(model, h, (rose[n] for n in board.blooms[p] if n in rose))
        supports(model, h, (reachable[n] for n in board.stands[p] if n in reachable))
    fixed_empty = board.floor - old_h - old_f - patch
    for p in old_f | rose.keys():
        if p in rose and board.around[p] & fixed_empty:
            model.add(rose[p] == 0)
        else:
            for n in board.around[p] & patch:
                if p in rose:
                    model.add_at_most_one(rose[p], walk[n])
                else:
                    model.add(walk[n] == 0)
    # Lexicographic objective within this patch: houses, then pots, then flowers.
    weight = len(patch) + 1
    score = weight**2 * sum(hive.values()) - weight * pots - sum(rose.values())
    if args.guard_edges:
        score -= weight**3 * sum(rose[p] for p in board.edge_beds & rose.keys())
    model.maximize(score)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.seconds
    solver.parameters.num_workers = args.workers
    status = solver.solve(model)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return houses, flowers
    return (old_h | {p for p, v in hive.items() if solver.value(v)},
            old_f | {p for p, v in rose.items() if solver.value(v)})


def optimize(board, houses, flowers, args, *, pot_limit=None, flower_limit=None):
    rng = random.Random(args.seed)
    if pot_limit is None:
        pot_limit = board.pots(flowers)
    if flower_limit is None:
        flower_limit = len(flowers)
    def rank(h, f):
        return (-len(f & board.edge_beds) if args.guard_edges else 0,
                len(h), -board.pots(f), -len(f))
    for sweep in range(args.passes):
        size = (7, 9, 8, 11, 12, 9)[sweep % 6]
        stride = max(4, size - 2)
        x0, y0 = -rng.randrange(stride), -rng.randrange(stride)
        origins = [(x, y) for x in range(x0, max(map(len, board.rows)), stride)
                   for y in range(y0, len(board.rows), stride)]
        rng.shuffle(origins)
        for x, y in origins:
            patch = {p for p in board.build if x <= p[0] < x+size and y <= p[1] < y+size}
            h, f = improve_patch(board, houses, flowers, patch, pot_limit, flower_limit, args)
            if (h != houses or f != flowers) and rank(h, f) >= rank(houses, flowers):
                board.verify(h, f)
                houses, flowers = h, f
                Path(args.output).write_text('\n'.join(board.grid(h, f)) + '\n')
        print(f'Pass {sweep+1}: {len(houses)} houses, {len(flowers)} roses, '
              f'{board.pots(flowers)} pots', flush=True)
    return houses, flowers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('terrain')
    parser.add_argument('layout')
    parser.add_argument('--output', help='write improved layouts here as they are found')
    parser.add_argument('--passes', type=int, default=4)
    parser.add_argument('--seconds', type=float, default=0.5, help='solver time per neighborhood')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--max-pots', type=int, help='garden pot budget (defaults to the starting count)')
    parser.add_argument('--max-flowers', type=int, help='flower budget (defaults to the starting count)')
    parser.add_argument('--side-only', action='store_true',
                        help='require a reachable pickup directly north, south, east or west of every house')
    parser.add_argument('--guard-edges', action='store_true',
                        help='require even flowers next to the map boundary to have eight mapped neighbors')
    args = parser.parse_args()
    if args.passes < 1 or not math.isfinite(args.seconds) or args.seconds <= 0 or args.workers < 1:
        parser.error('passes, seconds and workers must be positive')
    if args.output and Path(args.output).resolve() in {Path(args.terrain).resolve(), Path(args.layout).resolve()}:
        parser.error('use a separate output path')
    board = Island(read_grid(args.terrain), side_only=args.side_only)
    h, f = board.decode(read_grid(args.layout))
    board.verify(h, f)
    if args.max_pots is not None and args.max_pots < board.pots(f):
        parser.error('garden pot budget must accommodate the starting layout')
    if args.max_flowers is not None and args.max_flowers < len(f):
        parser.error('flower budget must accommodate the starting layout')
    print(f'Verified {len(h)} houses, {len(f)} roses, {board.pots(f)} pots', flush=True)
    if args.output:
        Path(args.output).write_text('\n'.join(board.grid(h, f)) + '\n')
        h, f = optimize(board, h, f, args, pot_limit=args.max_pots, flower_limit=args.max_flowers)
    if args.guard_edges and f & board.edge_beds:
        parser.exit(1, f'{len(f & board.edge_beds)} flowers still touch an uncharted tile\n')


if __name__ == '__main__':
    main()
