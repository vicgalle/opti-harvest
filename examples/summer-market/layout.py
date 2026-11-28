"""Fit, allocate and verify the summer market gardens on the two surveyed farms."""

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from apiary import STEPS, neighbors
from closed_walk import check_walk, tokens
from island_route import read_walk, shortest_paths
from machine_room import EXAMPLES as ROOM_PLANS, Room
from market_garden import HOPS_PER_BED, PRESETS, Budget, replay

TERRAINS = {
    'four-corners': HERE.parent / 'four-corners/terrain.txt',
    'everfarm': HERE.parent / 'boardwalk-apiary/everfarm-terrain.txt',
}
CODES = {'bean': 'c', 'berry': 'b', 'pepper': 'p', 'hops': 'h'}
BUILDINGS = {'N': (7, 4), 'D': (7, 3), 'T': (7, 3), 'O': (3, 3)}
RACKS = {'keg': 'K', 'jar': 'J', 'press': 'Q'}


def rectangle(x, y, w, h):
    return {(a, b) for a in range(x, x + w) for b in range(y, y + h)}


class Farm:
    def __init__(self, name):
        self.rows = TERRAINS[name].read_text().splitlines()
        self.base = {(x, y): c for y, row in enumerate(self.rows) for x, c in enumerate(row)}
        self.floor = {p for p, c in self.base.items() if c in 'P.WE'}
        self.build = {p for p, c in self.base.items() if c in 'P.'}
        self.soil = {p for p, c in self.base.items() if c == 'P'}
        if name == 'four-corners':
            self.home = (64, 17)
            self.public = {(40, 40), (39, 37), (40, 6), (76, 15), (63, 65), (17, 65), (8, 8)}
            # Preserve the original farmhouse, bin and greenhouse and their approaches.
            buildings = rectangle(59, 8, 9, 8) | rectangle(71, 14, 2, 1) | rectangle(35, 25, 8, 11)
            self.floor -= buildings
            protected = buildings | rectangle(58, 15, 16, 6) | rectangle(35, 36, 8, 1)
        else:
            (self.home,) = (p for p, c in self.base.items() if c == 'E')
            self.public = {self.home}
            protected = set()
        self.build -= protected | self.public | {self.home}
        self.soil &= self.build
        self.sides = {p: set(neighbors(p, STEPS)) & self.floor for p in self.floor}


def template(name, wing_offset=0):
    small = name == 'four-corners'
    nx, ny, y0 = (1, 1, 0) if small else (3, 2, 7)
    shape = {}
    for j in range(ny):
        for i in range(nx):
            for v in range(13):
                for u in range(13):
                    char = '+' if u in (0, 6, 12) or v in (0, 6, 12) else 'g'
                    if (u, v) == (6, 6):
                        char = 'S'
                    if u in (3, 9) and v in (3, 9):
                        char = 'I'
                    shape[16 * i + u, y0 + 16 * j + v] = char
    if small:
        buildings = {'N': (15, 0), 'D': (15, 8), 'O': (23, 1)}
        paving = rectangle(13, 5, 12, 2) | rectangle(13, 7, 1, 5) | rectangle(13, 11, 9, 1)
        lamps = {(14, 4), (23, 7)}
    else:
        buildings = {'D': (3, 1), 'N': (17, 0), 'O': (26, 1), 'T': (35, 1)}
        paving = rectangle(2, 4, 41, 2) | rectangle(0, 21, 45, 1)
        for x in (6, 22, 38):
            paving |= rectangle(x, 5, 1, 3) | rectangle(x, 19, 1, 5)
        for x in (13, 29):
            for y in (13, 29):
                paving |= rectangle(x, y, 3, 1)
        lamps = {(2, 3), (14, 4), (30, 4), (42, 3), (14, 20), (30, 22)}
    if small and wing_offset:
        buildings = {k: (x, y + wing_offset) for k, (x, y) in buildings.items()}
        paving = {(x, y + wing_offset) for x, y in paving} | rectangle(13, 6, 1, wing_offset + 1)
        lamps = {(x, y + wing_offset) for x, y in lamps}
    shape.update(dict.fromkeys(paving, '+'))
    for k, (x, y) in buildings.items():
        w, h = BUILDINGS[k]
        shape.update(dict.fromkeys(rectangle(x, y, w, h), k))
        shape.update(dict.fromkeys(rectangle(x, y + h, w, 1), '+'))
    shape.update(dict.fromkeys(lamps, 'L'))
    trees = [(3, -2), (9, -2)] if small else [(u, v) for u in (14, 30) for v in (10, 17, 26, 33)]
    shape.update(dict.fromkeys(trees, 'F'))
    top = min(y for x, y in shape)
    return {(x, y - top): c for (x, y), c in shape.items()}


def site(farm, name, peaches):
    distances, _ = shortest_paths(farm, farm.home, farm.floor)
    trials = []
    shapes = [template(name, offset) for offset in ((0, 4) if name == 'four-corners' else (0,))]
    for shape in shapes:
        slots = sorted(p for p, c in shape.items() if c == 'F')
        if peaches > len(slots):
            raise ValueError(f'this estate has room for {len(slots)} peach trees')
        for p in slots[peaches:]:
            del shape[p]
    for i, shape in enumerate(shapes):
        width = max(x for x, y in shape) + 1
        height = max(y for x, y in shape) + 1
        for (x, y), distance in distances.items():
            dx, dy = x - width // 2, y - height // 2
            if dx >= 0 and dy >= 0 and dx + width <= len(farm.rows[0]) and dy + height <= len(farm.rows):
                trials.append((distance, i, dx, dy, width))
    for _, i, dx, dy, width in sorted(trials):
        for mirror in (False, True):
            placed = {
                (dx + (width - 1 - x if mirror else x), dy + y): mark for (x, y), mark in shapes[i].items()
            }
            if all(p in (farm.soil if mark in 'gF' else farm.build) for p, mark in placed.items()) and all(
                rectangle(x - 1, y - 1, 3, 3) <= farm.build for (x, y), c in placed.items() if c == 'F'
            ):
                return placed
    raise ValueError('no compatible market site on this survey')


def fill_beds(tiles, plan):
    centers = sorted((p for p, c in tiles.items() if c == 'I'), key=lambda p: (p[1], p[0]))
    plants = plan['plants']
    sprinklers = plan['budget']['sprinklers']
    if sprinklers > len(centers):
        raise ValueError(f'this estate has room for {len(centers)} sprinklers')
    for p in centers[sprinklers:]:
        del tiles[p]
    centers = centers[:sprinklers]
    # Sorting the bed signatures breaks the permutation symmetry of identical beds.
    model = cp_model.CpModel()
    quantities, occupied, signatures = [], [], []
    for _ in centers:
        counts = {}
        for crop in CODES:
            capacity = HOPS_PER_BED if crop == 'hops' else 24
            n = model.new_int_var(0, capacity, crop)
            present = model.new_bool_var('present')
            model.add(n <= capacity * present)
            model.add(n >= present)
            occupied.append(present)
            counts[crop] = n
        quantities.append(counts)
        signatures.append(sum(counts[crop] * 25**i for i, crop in enumerate(CODES)))
        model.add(sum(counts.values()) <= 24)
    for a, b in zip(signatures, signatures[1:]):
        model.add(a >= b)
    for crop, total in plants.items():
        model.add(sum(row[crop] for row in quantities) == total)
    model.minimize(sum(occupied))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 6
    solver.parameters.max_time_in_seconds = 60
    if solver.solve(model) != cp_model.OPTIMAL:
        raise ValueError('bed arrangement lacks a certified minimum')
    for (x, y), counts in zip(centers, quantities):
        # A rim of trellises leaves the north-center cell open for hand picking.
        bed = rectangle(x - 2, y - 2, 5, 5) - {(x, y)}
        rim = sorted(
            (p for p in bed if max(abs(p[0] - x), abs(p[1] - y)) == 2 and p != (x, y - 2)),
            key=lambda p: (p[1], p[0]),
        )
        hops = rim[: solver.value(counts['hops'])]
        tiles.update(dict.fromkeys(hops, 'h'))
        rest = iter(sorted(bed - set(hops), key=lambda p: (p[1], p[0])))
        for crop in ('pepper', 'berry', 'bean'):
            for _ in range(solver.value(counts[crop])):
                tiles[next(rest)] = CODES[crop]
    return {p: c for p, c in tiles.items() if c != 'g'}


def interiors(name, budget):
    kind = 'shed' if name == 'four-corners' else 'big-shed'
    base = (ROOM_PLANS / f'{kind}-side.txt').read_text().splitlines()
    positions = [(x, y) for y in reversed(range(len(base))) for x, c in enumerate(base[y]) if c == 'M']
    halls = ('D',) if kind == 'shed' else ('D', 'T')
    supply = [RACKS[k] for k in ('press', 'jar', 'keg') for _ in range(getattr(budget, k))]
    if len(supply) > len(halls) * len(positions):
        raise ValueError('workshop capacity exceeded')
    # Keep pressing and preserves together. Fill from the entrance toward the back.
    result = {}
    for i, hall in enumerate(halls):
        size = (len(supply) + len(halls) - 1) // len(halls)
        machines = dict(zip(positions, supply[i * size : (i + 1) * size]))
        result[hall] = [
            ''.join(machines.get((x, y), '.' if c == 'M' else c) for x, c in enumerate(row))
            for y, row in enumerate(base)
        ]
    return result


def room_access(name, rows):
    base = (
        (ROOM_PLANS / ('shed-side.txt' if name == 'four-corners' else 'big-shed-side.txt'))
        .read_text()
        .splitlines()
    )
    if list(map(len, base)) != list(map(len, rows)):
        raise ValueError('wrong shed dimensions')
    for line, old in zip(rows, base):
        for c, orig in zip(line, old):
            if (orig in 'XEW' and c != orig) or (orig in '.M' and c not in '.KJQ'):
                raise ValueError('illegal shed tile')
    room = Room([line.translate(str.maketrans('KJQ', 'MMM')) for line in rows], side_only=True)
    ground = room.verify()
    return room.board, ground, {p: room.stands[p] & ground for p in room.machines}


def outside(farm, tiles, plan, name):
    b = Budget(**plan['budget'])
    marks = Counter(tiles.values())
    big = name == 'everfarm'
    if not set(marks) <= set('cbphISLNDTOF+') or tiles.keys() - farm.build:
        raise ValueError('illegal outdoor tile')
    if any(marks[c] != plan['plants'][crop] for crop, c in CODES.items()):
        raise ValueError('crop count differs from the production plan')
    if marks['I'] != b.sprinklers or b.cows > (8 if big else 4) or 28 * b.cows > 240:
        raise ValueError('field, barn or silo budget exceeded')
    trees = {p for p, c in tiles.items() if c == 'F'}
    if len(trees) != b.peaches or trees - farm.soil:
        raise ValueError('wrong orchard size or peach tree off soil')
    for x, y in trees:
        ring = rectangle(x - 1, y - 1, 3, 3)
        if (
            ring - farm.build
            or (ring - {(x, y)}) & tiles.keys()
            or any((u, v) != (x, y) and max(abs(u - x), abs(v - y)) < 3 for u, v in trees)
        ):
            raise ValueError('fruit tree lacks its clear growth square')
    ground = farm.floor - {p for p, c in tiles.items() if c in 'hISLNDTOF'}
    reached, _ = shortest_paths(farm, farm.home, ground)
    if farm.public - reached.keys():
        raise ValueError('a public route has been closed')
    fronts = {}
    for code in ('N', 'D', 'T', 'O') if big else ('N', 'D', 'O'):
        footprint = {p for p, c in tiles.items() if c == code}
        if not footprint:
            raise ValueError(f'missing building {code}')
        x, y = min(a for a, _ in footprint), min(b for _, b in footprint)
        w, h = BUILDINGS[code]
        if footprint != rectangle(x, y, w, h):
            raise ValueError(f'invalid footprint for {code}')
        fronts.update({p: {p} for p in rectangle(x, y + h, w, 1)})
    if (not big and marks['T']) or set(fronts) - reached.keys():
        raise ValueError('invalid or blocked building frontage')
    sprinklers, crows = ({p for p, c in tiles.items() if c == k} for k in 'IS')
    targets = {p: farm.sides[p] & reached.keys() for p in trees}
    memberships = defaultdict(set)
    for (x, y), c in tiles.items():
        if c not in 'cbph':
            continue
        sources = [q for q in sprinklers if max(abs(q[0] - x), abs(q[1] - y)) <= 2]
        if (
            (x, y) not in farm.soil
            or len(sources) != 1
            or not any((u - x) ** 2 + (v - y) ** 2 <= 64 for u, v in crows)
        ):
            raise ValueError(f'unprotected, unwatered or illegal crop at {(x, y)}')
        memberships[sources[0]].add(c)
        targets[x, y] = farm.sides[x, y] & reached.keys()
        if not targets[x, y]:
            raise ValueError(f'no side pickup at {(x, y)}')
    return ground, fronts, targets, sum(map(len, memberships.values()))


def cover(board, start, ground, targets):
    """Visit nearby unmet pickups, then take a shortest path home."""
    covers = defaultdict(set)
    for item, stands in targets.items():
        for p in stands:
            covers[p].add(item)
    remaining, walk = set(targets), [start]
    remaining -= covers[start]
    while remaining:
        q, parent = deque([walk[-1]]), {walk[-1]: None}
        while q:
            p = q.popleft()
            if covers[p] & remaining:
                break
            for n in sorted((board.sides[p] & ground) - parent.keys()):
                parent[n] = p
                q.append(n)
        else:
            raise ValueError('unreachable pickup')
        remaining -= covers[p]
        segment = []
        while parent[p] is not None:
            segment.append(p)
            p = parent[p]
        walk.extend(reversed(segment))
    _, parents = shortest_paths(board, start, ground)
    while walk[-1] != start:
        walk.append(parents[walk[-1]])
    return walk


def process(name, plan, directory, generate):
    replay(plan)
    farm = Farm(name)
    halls = ('D', 'T') if name == 'everfarm' else ('D',)
    if generate:
        tiles = fill_beds(site(farm, name, plan['budget']['peaches']), plan)
        rooms = interiors(name, Budget(**plan['budget']))
    else:
        rows = (directory / f'{name}-farm.txt').read_text().splitlines()
        if list(map(len, rows)) != list(map(len, farm.rows)):
            raise ValueError('wrong outdoor dimensions')
        tiles = {p: rows[p[1]][p[0]] for p, c in farm.base.items() if rows[p[1]][p[0]] != c}
        rooms = {k: (directory / f'{name}-{k}.txt').read_text().splitlines() for k in halls}
    ground, fronts, crops, count = outside(farm, tiles, plan, name)
    tasks = {'shops': (farm, farm.home, ground, fronts), 'full': (farm, farm.home, ground, fronts | crops)}
    stocks = Counter()
    for key, rows in rooms.items():
        board, free, pickups = room_access(name, rows)
        tasks[key] = (board, board.start, free, pickups)
        stocks.update(''.join(rows))
    if any(stocks[char] != plan['budget'][kind] for kind, char in RACKS.items()):
        raise ValueError('installed processing equipment differs from calendar')
    path = directory / f'{name}-walks.txt'
    if generate:
        walks = {k: cover(*spec) for k, spec in tasks.items()}
    else:
        directions = {
            key: moves for key, _, moves in (line.partition(' ') for line in path.read_text().splitlines())
        }
        walks = {k: read_walk(start, directions[k]) for k, (_, start, _, _) in tasks.items()}
    for key, (_, start, free, targets) in tasks.items():
        check_walk(start, free, targets, walks[key])
    if generate:
        directory.mkdir(parents=True, exist_ok=True)
        rows = [''.join(tiles.get((x, y), c) for x, c in enumerate(row)) for y, row in enumerate(farm.rows)]
        for suffix, lines in {'farm': rows, **rooms}.items():
            (directory / f'{name}-{suffix}.txt').write_text('\n'.join(lines) + '\n')
        path.write_text(''.join(f'{k} {tokens(w)}\n' for k, w in walks.items()))
    return count, {k: len(w) - 1 for k, w in walks.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('farm', choices=PRESETS)
    parser.add_argument('--plan', type=Path, help='use a different crop mix with the estate infrastructure')
    parser.add_argument(
        '--build', metavar='DIRECTORY', type=Path, help='write a fresh checked estate into this directory'
    )
    args = parser.parse_args()
    plan = json.loads((args.plan or HERE / f'{args.farm}.json').read_text())
    count, walks = process(args.farm, plan, args.build or HERE, bool(args.build))
    print(f'{count} crop/bed pairs; verified movement in tiles: {walks}')
