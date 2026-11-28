"""Replay the boardwalk builds and their collection routes on the saved farm surveys."""
import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from apiary import AROUND, BLOOM, STEPS, neighbors
from island_route import read_walk, shortest_paths

TEMPLATES = {10: 'short-boardwalk.txt', 29: 'boardwalk.txt'}


@dataclass(frozen=True)
class Pier:
    x: int
    y: int
    length: int
    vertical: bool

    def tile(self, u, v):
        return (self.x + v, self.y + u) if self.vertical else (self.x + u, self.y + v)

    def cells(self, templates):
        return {self.tile(u, v): c for v, row in enumerate(templates[self.length])
                for u, c in enumerate(row)}

    def ends(self):
        return (self.tile(1, 3), self.tile(self.length - 2, 3))


class Terrain:
    def __init__(self, name):
        self.rows = (HERE / f'{name}-terrain.txt').read_text().splitlines()
        self.base = {(x, y): c for y, row in enumerate(self.rows) for x, c in enumerate(row)}
        self.floor = {p for p, c in self.base.items() if c in 'P.WE'}
        self.build = {p for p, c in self.base.items() if c in 'P.'}
        self.soil = {p for p, c in self.base.items() if c == 'P'}
        self.home, = (p for p, c in self.base.items() if c == 'E')
        self.sides = {p: self.floor.intersection(neighbors(p, STEPS)) for p in self.floor}


def read_templates():
    result = {k: (HERE / file).read_text().splitlines() for k, file in TEMPLATES.items()}
    for length, rows in result.items():
        if (len(rows) != 7 or any(len(r) != length for r in rows)
                or set(''.join(rows)) - set('HFK+.')):
            raise ValueError('invalid boardwalk tile chart')
    return result


def read_records(path):
    return [line.split() for line in path.read_text().splitlines() if line and not line.startswith('#')]


def read_sites(path):
    sites = {}
    for label, x, y, length, direction in read_records(path):
        if label in sites or direction not in ('H', 'V') or int(length) not in TEMPLATES:
            raise ValueError(f'invalid site {label}')
        sites[label] = Pier(int(x), int(y), int(length), direction == 'V')
    return sites


def build(terrain, templates, sites):
    marks = {}
    footprint = set()
    for label, pier in sites.items():
        cells = pier.cells(templates)
        if cells.keys() - terrain.build or cells.keys() & footprint:
            raise ValueError(f'{label} overlaps another boardwalk or leaves buildable ground')
        houses, flowers, crows, lane = ({p for p, c in cells.items() if c == mark} for mark in 'HFK+')
        small = pier.length == 10
        if tuple(map(len, (houses, flowers, crows, lane))) != ((37, 2, 1, 22) if small else (111, 6, 2, 60)):
            raise ValueError(f'{label} has incorrect house, flower, scarecrow or lane counts')
        if flowers - terrain.soil:
            raise ValueError(f'{label} needs native tillable soil for every flower')
        for h in houses:
            if not flowers.intersection(neighbors(h, BLOOM)) or not terrain.sides[h] & lane:
                raise ValueError(f'{label} house {h} lacks a local flower or side pickup')
        for x, y in flowers:
            if not any((x-a)**2 + (y-b)**2 <= 64 for a, b in crows):
                raise ValueError(f'{label} flower {(x, y)} lacks scarecrow coverage')
        footprint.update(cells)
        marks.update({p: c for p, c in cells.items() if c != '.'})
    return marks


def verify(terrain, sites, records):
    templates = read_templates()
    marks = build(terrain, templates, sites)
    houses, flowers, crows, lanes = ({p for p, c in marks.items() if c == mark} for mark in 'HFK+')
    ground = terrain.floor - houses - crows
    reached, _ = shortest_paths(terrain, terrain.home, ground)
    if flowers - reached.keys():
        raise ValueError('a flower cannot be reached for replanting')
    unsafe = flowers | {q for f in flowers for q in neighbors(f, AROUND)}
    clear = ground - unsafe
    if terrain.home not in clear:
        raise ValueError('yard is obstructed')
    missing = set(sites)
    tours = defaultdict(list)
    for leg, *moves in records:
        # Daily schedules reuse the same physical sites with a different tour ID.
        if '/' in leg:
            group, label = leg.split('/', 1)
        else:
            group, label = leg[0], leg
        route = tours[group]
        if label.endswith('-home'):
            if label != group + '-home' or not route:
                raise ValueError(f'invalid return leg {label}')
        elif label not in missing:
            raise ValueError(f'duplicate or unknown boardwalk {label}')
        if route and route[-1] == terrain.home:
            raise ValueError(f'{group} continued after returning home')
        start = route[-1] if route else terrain.home
        walk = read_walk(start, ' '.join(moves))
        if any(p not in clear for p in walk) or any(b not in terrain.sides[a] for a, b in zip(walk, walk[1:])):
            raise ValueError(f'{label} leaves the flower-safe cardinal paths')
        if label.endswith('-home'):
            if walk[-1] != terrain.home:
                raise ValueError(f'{group} fails to return to the yard')
        else:
            pier = sites[label]
            # Suffix is the individual lap. Verify its pickups from the replay itself.
            cells = pier.cells(templates)
            lane = {p for p, c in cells.items() if c == '+'}
            lap = walk[-(len(lane)+1):]
            if (len(lap) != len(lane)+1 or lap[0] != lap[-1] or lap[0] not in pier.ends()
                    or lane != set(lap[:-1])):
                raise ValueError(f'{label} fails to complete its marked lap')
            pickups = {q for p in lap for q in terrain.sides[p]}
            if {p for p, c in cells.items() if c == 'H'} - pickups:
                raise ValueError(f'{label} leaves honey behind')
            missing.remove(label)
        if not route:
            route.append(start)
        route.extend(walk[1:])
    if missing or any(r[-1] != terrain.home for r in tours.values()):
        raise ValueError('incomplete collection schedule')
    xs, ys = zip(*houses)
    box = max(xs)-min(xs)+1, max(ys)-min(ys)+1
    active = houses | flowers | crows | lanes
    return marks, tours, box, len(active)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('farm', choices=('beach', 'everfarm'))
    parser.add_argument('--daily', action='store_true', help='replay the four-day Beach Farm rotation')
    parser.add_argument('--grid', action='store_true', help='print the full build as a tile chart')
    args = parser.parse_args()
    terrain = Terrain(args.farm)
    sites = read_sites(HERE / f'{args.farm}-sites.txt')
    if args.daily and args.farm != 'beach':
        parser.error('--daily is the Beach Farm four-day rotation')
    records = read_records(HERE / ('beach-daily.txt' if args.daily else f'{args.farm}-walks.txt'))
    marks, tours, box, active = verify(terrain, sites, records)
    if args.grid:
        for y, row in enumerate(terrain.rows):
            print(''.join(marks.get((x, y), c) for x, c in enumerate(row)))
        return
    print(f'{sum(c == "H" for c in marks.values()):,} houses across {box[0]} × {box[1]} tiles; '
          f'{active:,} distinct production and lap tiles')
    for group, route in tours.items():
        labels = [leg.split('/')[-1] for leg, *_ in records if leg.startswith(group) and not leg.endswith('-home')]
        count = sum(37 if sites[label].length == 10 else 111 for label in labels)
        print(f'{group}  {count:3} jars  {len(route)-1:4} steps from yard and back')


if __name__ == '__main__':
    main()
