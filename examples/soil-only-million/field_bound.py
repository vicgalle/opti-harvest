"""Check exact dual certificates for irrigated crop capacity and the 480-crop pot budget."""

import argparse
import gzip
import sys
from pathlib import Path

from ortools.linear_solver import linear_solver_pb2, pywraplp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from island import Island, read_grid

SCALE = 1_000_000


def build(pots=False):
    board = Island(read_grid(HERE.parent / 'mixed-farm' / 'terrain.txt'))
    soil = {p for p in board.beds if board.base[p] == 'S'}
    field = set()
    if pots:
        farm = read_grid(HERE.parent / 'mixed-farm' / 'farm.txt')
        field = {(x, y) for y, row in enumerate(farm) for x, value in enumerate(row) if value in 'C@'}
    forced = (board.floor - board.build) | field
    beds = board.beds if pots else soil
    roses = {p for p in beds - board.edge_beds - field if not board.around[p] & forced}
    area = {p for p in board.build - field if p in roses or board.blooms[p] & roses}
    outside = board.floor - area - field
    assert board.entries <= outside
    if not pots:
        assert soil <= area

    model = pywraplp.Solver.CreateSolver('GLOP')

    def variables(cells):
        return {p: model.NumVar(0, 1, '') for p in sorted(cells)}

    hive = variables(area)
    route = variables(area)
    rose = variables(roses)
    crop = variables(soil if not pots else set())
    sprinkler = variables(crop)
    for p in sorted(area):
        model.Add(hive[p] + route[p] + rose.get(p, 0)
                  + crop.get(p, 0) + sprinkler.get(p, 0) <= 1)
        model.Add(hive[p] <= model.Sum(rose[q] for q in sorted(board.blooms[p] & roses)))
        if not board.stands[p] & outside:
            model.Add(hive[p] <= model.Sum(route[q] for q in sorted(board.stands[p] & area)))
    for p in sorted(roses):
        for q in sorted(board.around[p] & area):
            model.Add(rose[p] <= hive[q] + rose.get(q, 0))
    model.Add(model.Sum(hive.values()) <= 48 * model.Sum(rose.values()))
    if pots:
        native = soil & roses
        native_area = {p for p in area if p in native or board.blooms[p] & native}
        non_native = area - native_area
        terrain_floor = board.floor - field
        native_interior = sum(not board.around[p] & (terrain_floor - native_area) for p in native_area)
        model.Add(3 * model.Sum(hive[p] for p in sorted(native_area))
                  + 2 * model.Sum(rose[p] for p in sorted(roses & native_area))
                  <= 3 * len(native_area) - native_interior)
        # Houses beyond all eligible native flowers must be assigned to a pot.
        # Bound each pot's contribution to a region by giving it free access
        # to the entire perimeter of its radius-five footprint in that region.
        regions = [non_native]
        for axis, cuts in ((0, (20, 40, 60)), (1, (10, 20, 30))):
            for cut in cuts:
                half = {p for p in non_native if p[axis] < cut}
                regions.extend([half, non_native - half])
        coverage = {q: {p for p in non_native if q in board.blooms[p]}
                    for q in sorted(roses - soil)}
        for region in regions:
            terms = []
            for q, cells in coverage.items():
                footprint = cells & region
                if footprint:
                    interior = sum(not board.around[p] & (terrain_floor - footprint) for p in footprint)
                    maximum = min(48, len(footprint) - (interior + 2) // 3)
                    terms.append(maximum * rose[q])
            model.Add(model.Sum(hive[p] for p in sorted(region)) <= model.Sum(terms))
    for x, y in sorted(crop):
        nearby = [(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)
                  if (dx or dy) and (x + dx, y + dy) in soil]
        model.Add(crop[x, y] <= model.Sum(sprinkler[q] for q in nearby))
    model.Add(model.Sum(crop.values()) <= 24 * model.Sum(sprinkler.values()))

    # Each reached tile chooses its predecessor on a four-direction walk from an entrance.
    # The walk may use the exterior freely. Dropping connectivity beyond these necessary
    # conditions makes this an upper bound for every possible crop-field shape.
    arcs = {}
    newly_seen = {p: [] for p in area}
    for p in sorted(area):
        incoming = []
        for q in sorted(board.sides[p] - field):
            arc = model.NumVar(0, 1, '')
            arcs[q, p] = arc
            incoming.append(arc)
            if q in area:
                model.Add(arc <= route[q])
            new_cells = (board.around[p] | {p}) - (board.around[q] | {q})
            for cell in new_cells & area:
                newly_seen[cell].append(arc)
        model.Add(route[p] == model.Sum(incoming))
    for p, q in sorted(arcs):
        if p < q and (q, p) in arcs:
            directed = arcs[p, q] + arcs[q, p]
            model.Add(directed <= route[p])
            model.Add(directed <= route[q])
    for p in sorted(area):
        if not board.around[p] & outside:
            model.Add(hive[p] + route[p] <= model.Sum(newly_seen[p]))

    model.Add(model.Sum(hive.values()) >= 1051)
    if pots:
        model.Maximize(-model.Sum(rose[q] for q in sorted(roses - soil)))
    else:
        model.Maximize(model.Sum(crop.values()))
    return model


def exact_bound(model, dual):
    """Multiply rows by signed integer weights, then bound the remaining box objective."""
    proto = linear_solver_pb2.MPModelProto()
    model.ExportModelToProto(proto)
    if len(dual) != len(proto.constraint):
        raise ValueError('dual certificate has the wrong number of constraints')
    residual = []
    for v in proto.variable:
        assert v.lower_bound == 0 and v.upper_bound == 1
        assert v.objective_coefficient.is_integer()
        residual.append(int(v.objective_coefficient) * SCALE)
    bound = 0
    for multiplier, row in zip(dual, proto.constraint):
        if not multiplier:
            continue
        rhs = row.upper_bound if multiplier > 0 else row.lower_bound
        assert rhs.is_integer()
        bound += multiplier * int(rhs)
        for col, coefficient in zip(row.var_index, row.coefficient):
            assert coefficient.is_integer()
            residual[col] -= multiplier * int(coefficient)
    return bound + sum(max(0, value) for value in residual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solve', action='store_true', help='regenerate dual weights with GLOP')
    parser.add_argument('--pots', action='store_true', help='bound pots for the published 480-crop field')
    args = parser.parse_args()
    target = HERE / ('pot-bound-dual.txt.gz' if args.pots else 'field-bound-dual.txt.gz')
    model = build(args.pots)
    if args.solve:
        if model.Solve() != pywraplp.Solver.OPTIMAL:
            raise RuntimeError('the LP solver did not return an optimal dual')
        dual = [round(row.dual_value() * SCALE) for row in model.constraints()]
        target.write_bytes(gzip.compress((' '.join(map(str, dual)) + '\n').encode(), mtime=0))
    else:
        dual = list(map(int, gzip.decompress(target.read_bytes()).split()))
    bound = exact_bound(model, dual)
    if args.pots:
        print(f'Certificate: pot count ≥ {-bound}/{SCALE}, hence at least {-(bound // SCALE)} pots.')
    else:
        print(f'Certificate: crop count ≤ {bound}/{SCALE}, hence at most {bound // SCALE} plants.')


if __name__ == '__main__':
    main()
