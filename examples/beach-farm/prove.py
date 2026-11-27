"""Certify the first five house maxima by enumerating undominated planting sites."""
import argparse
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ortools.sat.python import cp_model
from beach_farm import BeachFarm, distance, read_grid, read_order
from apiary import STEPS, neighbors


def upper_bound(farm, coverage, sites, seconds, target=None):
    spans = {p: coverage[p] for p in sites}
    model, houses, roses = farm.placement_model(spans, len(sites))
    # Every flower that is allowed can be planted simultaneously; the bed is behind the gate.
    for flower in roses.values():
        model.add(flower == 1)
    if target is not None:
        model.add(sum(houses.values()) >= target + 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 1
    status = solver.solve(model)
    if status == cp_model.INFEASIBLE and target is not None:
        return target
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return int(solver.best_objective_bound)
    if status == cp_model.UNKNOWN:
        return len(houses)
    raise RuntimeError(solver.status_name(status))


def separate_houses(farm, possible):
    """Group choices sharing a pickup or a walk connection outside the always-open main ground."""
    board = farm.exterior
    optional = possible & farm.outside
    fixed = farm.outside - optional
    # For grouping only, treat all fixed paths to the edge of the map window
    # as one exterior. The numerical bounds still use the real entrance.
    seeds = {p for p in fixed if p[0] in (0, len(board.rows[0])-1) or p[1] in (0, len(board.rows)-1)}
    main = set()
    for p in seeds | {board.start}:
        if p not in main:
            main.update(board.flood(p, fixed))
    rest = fixed - main
    representative = {}
    while rest:
        part = board.flood(min(rest), rest)
        representative.update(dict.fromkeys(part, min(part)))
        rest -= part
    edges = defaultdict(set)
    for h in possible:
        edges[h]
        near = set(neighbors(h, STEPS)) & farm.outside
        if h in optional or not near & main:
            for q in near - main:
                other = representative.get(q, q)
                edges[h].add(other)
                edges[other].add(h)
    pending = set(edges)
    while pending:
        visited = {next(iter(pending))}
        todo = list(visited)
        while todo:
            fresh = edges[todo.pop()] - visited
            visited.update(fresh)
            todo.extend(fresh)
        pending -= visited
        if visited & possible:
            yield frozenset(visited & possible)


def local_bound(farm, group, seconds):
    # Relax the model by granting pickup from any empty neighbor, including sealed pockets.
    model = cp_model.CpModel()
    placed = {p: model.new_bool_var('house') for p in sorted(group)}
    for p in group:
        near = set(neighbors(p, STEPS)) & farm.outside
        if not near - group:
            model.add_bool_or([~placed[p]] + [~placed[q] for q in near])
    model.maximize(sum(placed.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.max_time_in_seconds = seconds
    st = solver.solve(model)
    if st in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return int(solver.best_objective_bound)
    return len(group)


def certify(directory, seconds):
    farm = BeachFarm(read_grid(directory / 'terrain.txt'))
    build = read_grid(directory / 'build.txt')
    order = read_order(directory / 'planting-order.txt')
    sites = farm.coverage()
    singles = {p: upper_bound(farm, sites, (p,), seconds) for p in sites}
    pairs = {}

    def pair(p, q):
        key = tuple(sorted((p, q)))
        if key not in pairs:
            cap = singles[p] + singles[q]
            # Distant pairs keep the inexpensive sum bound. It is valid at any distance.
            if distance(p, q) <= 12:
                cap = min(cap, upper_bound(farm, sites, key, seconds))
            pairs[key] = cap
        return pairs[key]

    names = sorted(sites, key=lambda p: -singles[p])

    @lru_cache(None)
    def region_bound(group, full):
        if len(group) == 1:
            p = next(iter(group))
            return int(bool(set(neighbors(p, STEPS)) & farm.outside))
        if full:
            # All these sites have a flower in range in the original planting. Grant
            # that coverage for free and remove every house outside this region.
            return upper_bound(farm, {None: group}, (None,), seconds)
        return local_bound(farm, group, seconds)

    @lru_cache(None)
    def matching_bound(group):
        if len(group) < 2:
            return sum(singles[p] for p in group)
        p, *rest = group
        cap = singles[p] + matching_bound(tuple(rest))
        for i, q in enumerate(rest):
            cap = min(cap, pair(p, q) + matching_bound(tuple(rest[:i] + rest[i+1:])))
        return cap

    def contenders(prefix, start, left, value, target):
        if not left:
            yield prefix
            return
        for i in range(start, len(names) - left + 1):
            if value + sum(singles[p] for p in names[i:i+left]) <= target:
                break
            p = names[i]
            yield from contenders(prefix + (p,), i + 1, left - 1, value + singles[p], target)

    for k in range(1, 6):
        rows = farm.stage(build, order, k)
        target = len(farm.verify(rows)[0])
        largest = target
        direct = 0
        for group in contenders((), 0, k, 0, target):
            possible = set.union(*(sites[p] for p in group))
            if len(possible) <= target:
                continue
            cap = min(len(possible), matching_bound(group))
            if cap > target and k >= 3:
                regions = list(separate_houses(farm, possible))
                bounds = [len(r) for r in regions]
                for full in (False, True):
                    for i in sorted(range(len(regions)), key=lambda j: -len(regions[j])):
                        if sum(bounds) <= target:
                            break
                        bounds[i] = min(bounds[i], region_bound(regions[i], full))
                cap = min(cap, sum(bounds))
            if cap > target and k >= 3:
                cap = min(cap, upper_bound(farm, sites, group, seconds, target))
                direct += 1
            if cap > target:
                positions = tuple((x+16, y+41) for x,y in group)
                print(f'Open upper bound {cap} at {positions}', flush=True)
            largest = max(largest, cap)
        print(f'{k} flower(s): {target} houses in the build, upper bound {largest}; '
              f'{direct} groups needed a joint solve', flush=True)
        if largest > target:
            raise RuntimeError('bound remains open; increase --seconds per subproblem')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10, help='time per small CP-SAT model')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('time must be positive')
    certify(Path(__file__).resolve().parent, args.seconds)
