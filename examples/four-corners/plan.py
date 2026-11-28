"""Check the Four Corners apiary, or solve its equipment and planting plan again."""
import argparse
import sys
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from island import Island, read_grid
from island_route import read_walk, shortest_paths


# Coordinates are zero-based, with north at the top of the planner map.
# Each bed specification gives its first tile and its length.
BEDS = {
    'NE': [(45, 13, 12), (45, 20, 30), (45, 27, 30)],
    'SE': [(51, 46, 18), (58, 46, 18), (65, 46, 17), (72, 46, 14)],
    'SW': [(5, 47, 27), (5, 54, 28), (5, 61, 17)],
    'NW': [(7, 11, 18), (14, 11, 18), (21, 11, 17), (28, 11, 14)],
}
BOUNDS = {'NW': (3, 9, 35, 34), 'NE': (40, 8, 76, 34),
          'SW': (3, 44, 35, 66), 'SE': (46, 44, 76, 65)}
CABINS = [(14, 31), (25, 59), (43, 40)]
# The southeast grower has a second bed next to the shared clearing.
SIDE_BEDS = {'NE': (61, 33), 'SE': (36, 40), 'SW': (32, 60), 'NW': (32, 28)}
# Town-facing yard, farmhouse porch approach, north path, shrine, greenhouse
# steps, both side passages, big pond bank and quarry approach.
LANDMARKS = {(76, 15), (64, 16), (40, 6), (8, 8), (39, 37),
             (11, 40), (70, 40), (17, 65), (63, 64), (63, 65), (71, 15)}


def rectangle(x, y, width, height):
    return {(a, b) for a in range(x, x + width) for b in range(y, y + height)}


def corner_tiles(name):
    x, y, right, bottom = BOUNDS[name]
    return rectangle(x, y, right - x + 1, bottom - y + 1)


def side_bed(name):
    x, y = SIDE_BEDS[name]
    return rectangle(x - 2, y - 2, 5, 5)


def cabin_sites():
    footprint = set().union(*(rectangle(x, y, 5, 3) for x, y in CABINS))
    frontage = set().union(*(rectangle(x, y + 3, 5, 1) for x, y in CABINS))
    return footprint, frontage


def read_laps():
    laps = {}
    for line in (HERE / 'walks.txt').read_text().splitlines():
        name, x, y, moves = line.split(maxsplit=3)
        if name in laps:
            raise ValueError(f'duplicate walk for {name}')
        laps[name] = read_walk((int(x), int(y)), moves)
    if laps.keys() != BOUNDS.keys():
        raise ValueError('expected one lap in each corner')
    return laps


def garden_rows(name):
    vertical = name in ('SE', 'NW')
    return [[(x, y + i) if vertical else (x + i, y) for i in range(length)]
            for x, y, length in BEDS[name]]


def nearby(p, q, radius):
    return max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= radius


def crow_range(p, q):
    # Inscribed in the ordinary scarecrow's in-game footprint.
    return (p[0] - q[0])**2 + (p[1] - q[1])**2 <= 64


def verify(board, rows, laps):
    if list(map(len, rows)) != list(map(len, board.rows)):
        raise ValueError('layout dimensions differ from the terrain')
    sites = {mark: set() for mark in 'HFCIKc+'}
    for p, original in board.base.items():
        x, y = p
        mark = rows[y][x]
        if mark == original:
            continue
        allowed = board.beds if mark in 'FC' else board.floor if mark == '+' else board.build
        if mark not in sites or p not in allowed:
            raise ValueError(f'illegal {mark!r} at {p}')
        sites[mark].add(p)

    houses, flowers, crops = (sites[k] for k in 'HFC')
    sprinklers, crows, cabins, lanes = (sites[k] for k in 'IKc+')
    pads, doors = cabin_sites()
    if pads != cabins:
        raise ValueError('expected three clear 5×3 cabin footprints')
    open_ground = board.floor - houses - sprinklers - crows - cabins
    reached = board.flood(board.start, open_ground)
    missing = (flowers | crops | doors | LANDMARKS) - reached
    if missing:
        raise ValueError(f'unreachable plant, frontage or landmark at {min(missing)}')
    for plant in flowers | crops:
        if not any(nearby(plant, s, 2) for s in sprinklers):
            raise ValueError(f'unwatered plant at {plant}')
        if not any(crow_range(plant, k) for k in crows):
            raise ValueError(f'missing scarecrow coverage at {plant}')

    # Avoid even diagonal flower interactions on both the lap and its approach.
    unsafe = flowers | set().union(*(board.around[f] for f in flowers))
    distances, _ = shortest_paths(board, board.start, open_ground - unsafe - crops)
    if (doors | LANDMARKS) - distances.keys():
        raise ValueError('a cabin frontage or public approach requires entering a crop or passing a flower')
    seen, collected, counted_crops, results = set(), set(), set(), {}
    for name, walk in laps.items():
        stops = set(walk[:-1])
        if (len(walk) != 175 or walk[0] != walk[-1] or len(stops) != 174 or
                stops - lanes or stops & (unsafe | seen) or walk[0] not in distances or
                any(b not in board.sides[a] for a, b in zip(walk, walk[1:]))):
            raise ValueError(f'{name} needs a reachable 174-step simple lap clear of flowers')
        seen |= stops
        sector = corner_tiles(name) | side_bed(name)
        allotment = crops & sector
        if len(allotment) != 75 or counted_crops & allotment:
            raise ValueError(f'{name} needs a separate allotment of 75 crops')
        counted_crops |= allotment
        picked = houses & set().union(*(board.sides[p] for p in stops))
        if len(picked) != 300 or picked != houses & sector:
            raise ValueError(f'{name} lap reaches {len(picked)} houses')
        for h in picked:
            if not board.blooms[h] & flowers & sector:
                raise ValueError(f'{name} house {h} needs a local flower')
        collected |= picked
        results[name] = (len(flowers & sector), len(crops & sector), len(sprinklers & sector),
                         len(crows & sector), distances[walk[0]])
    if seen != lanes or collected != houses or counted_crops != crops:
        raise ValueError('stray path, house or crop outside the four allotments')
    return results


def solve_corner(board, name, walk, seconds):
    model = cp_model.CpModel()
    stops = set(walk)
    beds = garden_rows(name)
    garden = set().union(*beds)
    if garden - board.beds:
        raise ValueError(f'{name} beds leave the tillable soil')
    caps = {p for bed in beds for p in (bed[0], bed[-1])}
    pads, doors = cabin_sites()
    side_fields = set().union(*(side_bed(n) for n in BOUNDS))
    # Keep the public approach open even when all four side beds are planted.
    _, parents = shortest_paths(board, board.start, board.floor - garden - pads - side_fields)
    approach = {walk[0]}
    p = walk[0]
    while p != board.start:
        p = parents[p]
        approach.add(p)
    build = (board.build & corner_tiles(name)) - stops - approach - pads - doors - LANDMARKS - side_fields
    rose_sites = {p for p in garden if not board.around[p] & stops}
    rose = {p: model.new_bool_var('flower') for p in sorted(rose_sites)}
    beside_lap = set().union(*(board.sides[p] for p in stops))
    house = {p: model.new_bool_var('house') for p in sorted((build & beside_lap) - garden)
             if board.blooms[p] & rose_sites}
    sprinkler = {p: model.new_bool_var('iridium') for p in sorted(build - (garden - caps))
                 if any(nearby(p, f, 2) for f in garden)}
    scarecrow = {p: model.new_bool_var('scarecrow') for p in sorted(build - garden)
                 if any(nearby(p, f, 3) for f in garden)}

    for p in build:
        model.add(house.get(p, 0) + sprinkler.get(p, 0) + scarecrow.get(p, 0) <= 1)
    for bed in beds:
        # Either end opens directly onto the lap. Keep at least one open so the
        # entire planting row can be tended with all the equipment in place.
        model.add(sprinkler.get(bed[0], 0) + sprinkler.get(bed[-1], 0) <= 1)
    for p, h in house.items():
        model.add_bool_or(rose[f] for f in sorted(board.blooms[p] & rose_sites)).only_enforce_if(h)
    extra_sprinkler = SIDE_BEDS[name]
    x, y = extra_sprinkler
    extra_crow = (x, y - 1)
    for f in garden:
        if not nearby(f, extra_sprinkler, 2):
            model.add_bool_or(v for p, v in sprinkler.items() if nearby(f, p, 2))
        if not crow_range(f, extra_crow):
            model.add_bool_or(v for p, v in scarecrow.items() if crow_range(f, p))
    model.add(sum(house.values()) == 300)
    # Favor fewer sprinklers, then leave as much of the garden as possible for crops.
    lost_crops = sum(rose.values()) + sum(sprinkler[p] for p in caps & sprinkler.keys())
    extra_soil = (side_bed(name) & board.beds) - {extra_sprinkler, extra_crow}
    model.add(len(garden) - lost_crops + len(extra_soil) >= 75)
    model.minimize(10000 * sum(sprinkler.values()) + 100 * lost_crops + sum(scarecrow.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 4
    solver.parameters.max_time_in_seconds = seconds
    status = solver.solve(model)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        raise RuntimeError(f'{name} search returned {solver.status_name(status)}')
    result = dict.fromkeys(garden, 'C') | dict.fromkeys(stops, '+')
    for mark, variables in [('H', house), ('F', rose), ('I', sprinkler), ('K', scarecrow)]:
        result.update(dict.fromkeys((p for p, v in variables.items() if solver.value(v)), mark))
    result[extra_sprinkler] = 'I'
    result[extra_crow] = 'K'
    needed = 75 - sum(c == 'C' for c in result.values())
    patch = sorted(extra_soil, key=lambda p: (p[1], p[0]))
    result.update(dict.fromkeys(patch[:needed], 'C'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--solve', metavar='OUTPUT', type=Path, help='save a freshly solved and checked plan')
    mode.add_argument('--check', type=Path, default=HERE / 'farm.txt', help='check a saved tile plan')
    parser.add_argument('--seconds', type=float, default=30, help='solver time limit per corner')
    args = parser.parse_args()
    board = Island(read_grid(HERE / 'terrain.txt'), side_only=True)
    laps = read_laps()
    if args.solve:
        if args.seconds <= 0:
            parser.error('--seconds must be positive')
        if args.solve.resolve() in {(HERE / f).resolve() for f in ('terrain.txt', 'walks.txt')}:
            parser.error('use a separate output path')
        changes = dict.fromkeys(cabin_sites()[0], 'c')
        for name, walk in laps.items():
            changes.update(solve_corner(board, name, walk, args.seconds))
        rows = [''.join(changes.get((x, y), tile) for x, tile in enumerate(row))
                for y, row in enumerate(board.rows)]
    else:
        rows = read_grid(args.check)
    results = verify(board, rows, laps)
    if args.solve:
        args.solve.write_text('\n'.join(rows) + '\n')
    for name, (flowers, crops, sprinklers, crows, approach) in results.items():
        print(f'{name}: 300 side pickups in 174 steps, {flowers} flowers, {crops} crops, '
              f'{sprinklers} iridium sprinklers, {crows} scarecrows, {approach} steps from the hub')


if __name__ == '__main__':
    main()
