"""Prove the protected bee-house maximum for a single sprinkler on an open field."""

import argparse
from collections import defaultdict
from itertools import product

from ortools.linear_solver import pywraplp


STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
SQUARE = tuple(product(range(-1, 2), repeat=2))
SPRINKLER = (0, 0)
# Watering radius and independently attainable house count. The basic tier waters a cross.
TIERS = {'basic': (1, 64), 'quality': (1, 76), 'iridium': (2, 113), 'nozzle': (3, 155)}


def shift(p, offset):
    return p[0] + offset[0], p[1] + offset[1]


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def solve(seconds, relaxed, tier='nozzle', flower_budget=None, exceed=None, side_only=False):
    solver = pywraplp.Solver.CreateSolver('SCIP')
    solver.SetNumThreads(1)
    solver.set_time_limit(int(seconds * 1000))
    solver.SetSolverSpecificParametersAsString('limits/gap = 0.00001\nseparating/maxroundsroot = 15')
    radius, count = TIERS[tier]
    beds = set(STEPS) if tier == 'basic' else set(product(range(-radius, radius+1), repeat=2)) - {SPRINKLER}
    reach = radius + 5
    board = {p for p in product(range(-reach, reach+1), repeat=2) if any(manhattan(p, f) <= 5 for f in beds)}
    usable = board - {SPRINKLER}
    pickup = STEPS + ((0, 0),) if side_only else SQUARE
    pickup_distance = manhattan if side_only else chebyshev
    interior = {p for p in board if all(shift(p, d) in board for d in pickup)}

    def flags(name, points):
        return {p: solver.BoolVar(f'{name}{p}') for p in sorted(points)}

    house = flags('house', usable)
    flower = flags('flower', beds)
    walk = flags('walk', usable)
    parent = {}
    enters = defaultdict(list)
    new_coverage = defaultdict(list)

    for p in sorted(usable):
        for d in STEPS:
            prior = shift(p, d)
            if prior == SPRINKLER:
                continue
            edge = (p, prior)
            var = solver.BoolVar(f'parent{edge}')
            parent[edge] = var
            enters[p].append(edge)
            if prior in usable:
                solver.Add(var <= walk[prior])
            # Charge each interior tile to an edge that first brings it within pickup reach.
            for offset in pickup:
                target = shift(p, offset)
                if target in interior and pickup_distance(target, prior) > 1:
                    new_coverage[target].append(var)
        solver.Add(sum(parent[e] for e in enters[p]) == walk[p])
        solver.Add(house[p] + flower.get(p, 0) + walk[p] <= 1)
        solver.Add(house[p] <= sum(flower[f] for f in beds if manhattan(p, f) <= 5))
        if p in beds:
            for offset in set(SQUARE) - {(0, 0)}:
                q = shift(p, offset)
                if q in usable:
                    solver.Add(flower[p] + walk[q] <= 1)
        if p in interior:
            stands = [shift(p, d) for d in pickup if d != (0, 0)]
            solver.Add(house[p] <= sum(walk[q] for q in stands if q in usable))

    for p in sorted(interior & usable):
        solver.Add(house[p] + walk[p] <= sum(new_coverage[p]))

    if not relaxed:
        # Redundant connectivity cuts tighten the linear relaxation. A route
        # reaching an interior square has to cross its cardinal boundary.
        for radius in range(1, 8):
            for center in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                inside = {p for p in usable if chebyshev(p, center) < radius}
                boundary = {shift(p, d) for p in inside for d in STEPS} - inside - {SPRINKLER}
                if boundary <= usable:
                    for p in inside:
                        solver.Add(walk[p] <= sum(walk[q] for q in boundary))

        # A unit of flow is consumed at every chosen standing tile. Only
        # exterior parent edges may supply flow without receiving any.
        flow = {e: solver.NumVar(0, len(usable), f'flow{e}') for e in parent}
        for edge, var in flow.items():
            solver.Add(var <= len(usable) * parent[edge])
        for p in walk:
            prior_tiles = [shift(p, d) for d in STEPS]
            solver.Add(sum(flow[e] for e in enters[p]) - sum(flow[q, p] for q in prior_tiles if (q, p) in flow) == walk[p])

        target = count + 1 if flower_budget is None else count
        if exceed is not None:
            target = exceed + 1
        solver.Add(sum(house.values()) >= target)
        if flower_budget is not None:
            solver.Add(sum(flower.values()) <= flower_budget)

    solver.Maximize(sum(house.values()))
    status = solver.Solve()
    if relaxed and status == pywraplp.Solver.OPTIMAL:
        print(f'Relaxed model optimum {solver.Objective().Value():.0f}')
        return
    if not relaxed and status == pywraplp.Solver.INFEASIBLE:
        if exceed is not None:
            print(f'{tier}: proved a house upper bound of {exceed} for the requested rules.')
        elif flower_budget is None:
            print(f'{tier}: INFEASIBLE at {count+1} houses. The {count}-house build attains the bound.')
        else:
            print(f'{tier}: {count} houses need more than {flower_budget} flowers.')
        return
    if not relaxed and status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise SystemExit(f'The model admits a solution with {solver.Objective().Value():.0f} houses. '
                         'The requested upper bound does not follow.')
    raise SystemExit(f'Proof incomplete (solver status {status}). Increase --seconds to continue the check.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=600, help='time limit for this solve')
    parser.add_argument('--tier', choices=TIERS, default='nozzle')
    parser.add_argument('--relaxed', action='store_true', help='omit root flow and optimize the relaxation')
    parser.add_argument('--at-most-flowers', type=int, metavar='N',
                        help='test whether N flowers could supply the published maximum house count')
    parser.add_argument('--exceed', type=int, metavar='H', help='test whether H+1 houses can fit')
    parser.add_argument('--side-only', action='store_true', help='check four-direction pickup with --exceed')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('the time limit must be positive')
    if args.side_only and args.exceed is None:
        parser.error('choose the side-pickup house count to test with --exceed')
    if args.relaxed and args.exceed is not None:
        parser.error('the relaxation maximizes house count directly; omit --exceed')
    if args.at_most_flowers is not None and (args.relaxed or args.at_most_flowers < 0):
        parser.error('a flower-budget proof needs a nonnegative budget and the connected model')
    solve(args.seconds, args.relaxed, args.tier, args.at_most_flowers, args.exceed, args.side_only)
