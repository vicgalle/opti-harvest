"""Rebuild and check the two-gate honey and crop courtyard, including its tea hedge."""

import argparse
from collections import Counter, deque
from pathlib import Path

from plan import GATE, distance, neighbors


SIZE = 30
INNER_GATE = (14, 2)


def build(ordinary=False):
    tiles = {(x, y): '.' for x in range(SIZE) for y in range(SIZE)}
    ring = {(x, y) for x in range(1, SIZE - 1) for y in range(1, SIZE - 1)
            if min(x, y) == 1 or max(x, y) == SIZE - 2}
    for p in ring:
        tiles[p] = '+'
    for p in set().union(*(neighbors(p) for p in ring)) - ring:
        tiles[p] = 'H'
    tiles[GATE] = 'G'
    tiles[INNER_GATE] = 'g'

    # A sprinkler with a rose on either side repeats every seven tiles.
    # At a corner the two runs share one rose.
    for center in range(4, SIZE - 4, 7):
        for side in (3, SIZE - 4):
            for offset, mark in ((-1, 'F'), (0, 'S'), (1, 'F')):
                tiles[center + offset, side] = mark
                tiles[side, center + offset] = mark
    flowers = [p for p, char in tiles.items() if char == 'F']
    for x, y in flowers:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = x + dx, y + dy
                if tiles[p] == '.':
                    tiles[p] = 'T'

    for x in range(5, 25):
        for y in range(5, 25):
            tiles[x, y] = 'v'
    for x in range(7, 25, 5):
        for y in range(7, 25, 5):
            tiles[x, y] = 'I'
    if ordinary:
        for x in (9, 20):
            for y in (9, 20):
                tiles[x, y] = 'C'
    else:
        for p in ((4, 13), (25, 16)):
            tiles[p] = 'D'
    return [''.join(tiles[x, y] for x in range(SIZE)) for y in range(SIZE)]


def flood(start, allowed):
    visited = {start}
    queue = deque(visited)
    while queue:
        fresh = (neighbors(queue.popleft()) & allowed) - visited
        queue.extend(fresh)
        visited |= fresh
    return visited


def verify(rows):
    if len(rows) != SIZE or any(len(row) != SIZE for row in rows):
        raise ValueError('expected a 30×30 courtyard')
    tiles = {(x, y): c for y, row in enumerate(rows) for x, c in enumerate(row)}
    valid = '.GHFSIDC+gvT'
    if set(tiles.values()) - set(valid):
        raise ValueError('unknown tile symbol')
    sites = {c: {p for p, mark in tiles.items() if mark == c} for c in valid}
    if sites['G'] != {GATE} or sites['g'] != {INNER_GATE}:
        raise ValueError('a gate is missing')

    x, y = GATE
    stops = [(x, y)]
    for dx, dy, steps in ((1, 0, 1), (1, 0, 27), (0, 1, 27),
                          (-1, 0, 27), (0, -1, 27), (-1, 0, 1)):
        for _ in range(steps):
            x, y = x + dx, y + dy
            if tiles.get((x, y)) not in ('+', 'G'):
                raise ValueError(f'obstructed honey route at {(x, y)}')
            stops.append((x, y))
    lap = set(stops[1:-1])
    if stops[-1] != GATE or lap != sites['+'] or len(lap) != 108:
        raise ValueError('incorrect closed lap')
    if len(sites['H']) != 2 * len(lap) - 6:
        raise ValueError('wrong house count for a two-gate lap')
    for p in sites['H']:
        if not lap & neighbors(p) or not any(distance(p, f) <= 5 for f in sites['F']):
            raise ValueError(f'missing side pickup or flower at {p}')

    walkable = set().union(*(sites[char] for char in 'Gg+.Fv'))
    reached = flood(GATE, walkable)
    if not sites['v'] <= reached or reached & sites['F']:
        raise ValueError('an unreachable crop or an exposed rose')
    if flood(GATE, walkable - sites['g']) & sites['v']:
        raise ValueError('the reported inner gate does not separate the crop field')
    for x, y in sites['F']:
        if not neighbors((x, y)) & sites['S']:
            raise ValueError(f'a rose lacks basic sprinkler coverage at {(x, y)}')
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (dx or dy) and tiles.get((x + dx, y + dy)) not in ('H', 'T', 'C', 'D', 'S', 'I'):
                    raise ValueError(f'open approach to rose at {(x, y)}')
        # Each perimeter rose can be replanted by temporarily lifting one house
        # between the rose and the lap, then replacing it.
        if not any(neighbors(h) & lap for h in neighbors((x, y)) & sites['H']):
            raise ValueError(f'no single-house maintenance opening at {(x, y)}')
    for x, y in sites['v']:
        if not any(max(abs(x - a), abs(y - b)) <= 2 for a, b in sites['I']):
            raise ValueError(f'crop lacks iridium sprinkler water at {(x, y)}')

    # A regular scarecrow reaches at least six tiles along both axes
    # simultaneously. The deluxe check is conservative within a radius of 16.
    for x, y in sites['F'] | sites['v']:
        ordinary = any(max(abs(x-a), abs(y-b)) <= 6 for a, b in sites['C'])
        deluxe = any((x-a)**2 + (y-b)**2 <= 16**2 for a, b in sites['D'])
        if not (ordinary or deluxe):
            raise ValueError(f'crop or rose outside scarecrow coverage at {(x, y)}')

    tea_side = sum(bool(neighbors(p) & reached) for p in sites['T'])
    for x, y in sites['T']:
        if not any((x + dx, y + dy) in reached for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            raise ValueError(f'unharvestable tea bush at {(x, y)}')
    counts = Counter(tiles.values())
    return (f"{counts['H']} houses | {len(lap)} lap steps | {len(stops)-1} gate-to-gate steps\n"
            f"{counts['v']} reachable watered crops | {counts['F']} protected watered roses | "
            f"{counts['T']} reachable tea bushes ({tea_side} from the side)\n"
            f"{counts['I']} iridium and {counts['S']} basic sprinklers | "
            f"{counts['C']} ordinary and {counts['D']} deluxe scarecrows")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ordinary', action='store_true', help='use four ordinary scarecrows')
    parser.add_argument('--check', type=Path, help='read and verify a saved grid')
    parser.add_argument('--grid', action='store_true', help='also print the build plan')
    args = parser.parse_args()
    if args.check and args.ordinary:
        parser.error('choose --check or --ordinary')
    rows = args.check.read_text().splitlines() if args.check else build(args.ordinary)
    print(verify(rows))
    if args.grid:
        print('\n'.join(rows))
