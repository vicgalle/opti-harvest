"""Replay four-way access in the published grid, including seasonal maintenance."""

from collections import deque
from itertools import product
from pathlib import Path


COMPASS = {'E': (1, 0), 'W': (-1, 0), 'S': (0, 1), 'N': (0, -1)}
DIRECTIONS = tuple(COMPASS.values())
PICKUPS = set(product(range(-1, 2), repeat=2)) - {(0, 0)}
# One-based columns and rows, matching the build map.
SERVICE_HOUSES = ((6, 8), (13, 6), (9, 13), (14, 12))


def adjacent(p, offsets):
    return {(p[0] + dx, p[1] + dy) for dx, dy in offsets}


def reachable(board, solid, start=(1, 1)):
    reached = {start}
    queue = deque(reached)
    while queue:
        fresh = (adjacent(queue.popleft(), DIRECTIONS) & board) - solid - reached
        reached |= fresh
        queue.extend(fresh)
    return reached


def verify(rows):
    if len(rows) != 19 or any(len(row) != 19 for row in rows):
        raise ValueError('expected a 19×19 build')
    tiles = {(x, y): c for y, row in enumerate(rows, 1) for x, c in enumerate(row, 1)}
    if set(tiles.values()) - set('HSFC.'):
        raise ValueError('unknown tile symbol')
    sites = {c: {p for p, mark in tiles.items() if mark == c} for c in 'HSFC.'}
    beds, houses, crows = sites['F'], sites['H'], sites['C']
    if sites['S'] != {(10, 10)} or len(houses) != 155 or len(beds) != 12 or len(crows) != 2:
        raise ValueError('incorrect count or sprinkler location')
    blocked = houses | crows | sites['S']
    board = set(tiles)
    for obstacles in (blocked, (blocked - crows) | {(18, 18)}):
        reached = reachable(board, obstacles)
        if beds & reached or any(adjacent(p, PICKUPS) & reached for p in beds):
            raise ValueError('at least one flower can be picked from accessible ground')
        if any(not adjacent(p, PICKUPS) & reached for p in houses):
            raise ValueError('unreachable honey')
    for x, y in houses:
        if not any(abs(x-a) + abs(y-b) <= 5 for a, b in beds):
            raise ValueError(f'unflavored honey at {(x, y)}')
    for x, y in beds:
        if max(abs(x-10), abs(y-10)) > 3:
            raise ValueError(f'flower outside nozzle coverage at {(x, y)}')
        if adjacent((x, y), PICKUPS) - blocked - beds:
            raise ValueError(f'a gap in the house and flower shield at {(x, y)}')
        if not any((x-a)**2 + (y-b)**2 <= 64 for a, b in crows):
            raise ValueError(f'flower outside ordinary scarecrow coverage at {(x, y)}')
        if (x-18)**2 + (y-18)**2 > 16**2:
            raise ValueError('alternate deluxe scarecrow does not cover this flower')

    reached = reachable(board, blocked)
    served = set()
    for p in SERVICE_HOUSES:
        if p not in houses or not adjacent(p, DIRECTIONS) & reached:
            raise ValueError(f'cannot lift the maintenance house from the side at {p}')
        cluster = beds & reachable(board, blocked - {p})
        if len(cluster) != 3 or cluster & served:
            raise ValueError(f'incorrect rose access through {p}')
        served |= cluster
    if served != beds:
        raise ValueError('some flowers cannot be replanted')
    print('155 collectible flower-honey houses, 12 fully shielded and watered roses, '
          '2 ordinary scarecrows, and 4 independent replanting openings verified in 19×19.')


def verify_tier(rows, tier, radius, count, *, side_only=False, flower_count=4, walk=None):
    size = 2 * (radius + 5) + 1
    if len(rows) != size or any(len(row) != size for row in rows):
        raise ValueError(f'incorrect {tier} footprint')
    # Add a ring of open ground so even houses at the edge can be picked up from outside.
    board = set(product(range(size+2), repeat=2))
    tiles = {(x, y): ch for y, row in enumerate(rows, 1) for x, ch in enumerate(row, 1)}
    if set(tiles.values()) - set('HFSCD.'):
        raise ValueError(f'invalid {tier} grid symbol')
    center = size // 2 + 1
    houses = {p for p, ch in tiles.items() if ch == 'H'}
    flowers = {p for p, ch in tiles.items() if ch == 'F'}
    sprinklers = {p for p, ch in tiles.items() if ch == 'S'}
    if sprinklers != {(center, center)} or len(houses) != count:
        raise ValueError(f'incorrect {tier} house count or sprinkler location')
    crows = {p for p, ch in tiles.items() if ch in 'CD'}
    if len(crows) != 1 or len(flowers) != flower_count:
        raise ValueError(f'incorrect flower or scarecrow count in the {tier} build')
    start = (0, center)
    reached = reachable(board, houses | sprinklers | crows, start)
    for x, y in flowers:
        if not any((x-a)**2+(y-b)**2 <= (16 if tiles[a, b] == 'D' else 8)**2 for a, b in crows):
            raise ValueError(f'flower outside {tier} scarecrow coverage')
        offset = (x-center, y-center)
        watered = offset in DIRECTIONS if tier == 'basic' else max(map(abs, offset)) <= radius
        if not watered or (x, y) in reached or adjacent((x, y), PICKUPS) & reached:
            raise ValueError(f'unwatered or exposed {tier} flower at {(x, y)}')
    for x, y in houses:
        if not adjacent((x, y), DIRECTIONS if side_only else PICKUPS) & reached or not any(
                abs(x-a)+abs(y-b) <= 5 for a, b in flowers):
            raise ValueError(f'uncollectible or unflavored {tier} house at {(x, y)}')
    pickups = 'side-only' if side_only else 'collectible'
    print(f'{tier}: {count} {pickups} houses and {len(flowers)} protected, watered flowers')
    if walk is not None:
        position = start
        visited = {start}
        steps = 0
        for token in walk.split():
            if token[0] not in COMPASS or not token[1:].isdigit() or int(token[1:]) < 1:
                raise ValueError(f'invalid walk instruction {token}')
            dx, dy = COMPASS[token[0]]
            for _ in range(int(token[1:])):
                position = (position[0] + dx, position[1] + dy)
                if position not in reached:
                    raise ValueError(f'walk leaves accessible ground at {position}')
                visited.add(position)
                steps += 1
        offsets = DIRECTIONS if side_only else PICKUPS
        if position != start or any(not adjacent(h, offsets) & visited for h in houses):
            raise ValueError('walk must collect every jar and return to the entrance')
        print(f'{steps} steps from the west entrance and back, all {count} pickups verified')


if __name__ == '__main__':
    directory = Path(__file__).resolve().parent
    for name, radius, total in [('basic', 1, 64), ('quality', 1, 76), ('iridium', 2, 113)]:
        verify_tier((directory / (name + '.txt')).read_text().splitlines(), name, radius, total)
    verify_tier((directory / 'nozzle-four.txt').read_text().splitlines(), 'nozzle', 3, 148,
                walk=(directory / 'nozzle-four-walk.txt').read_text())
    for name, radius, total, n in [('basic', 1, 56, 2), ('quality', 1, 70, 7), ('iridium', 2, 98, 9)]:
        verify_tier((directory / (name + '-side.txt')).read_text().splitlines(),
                    name, radius, total, side_only=True, flower_count=n)
    verify((directory / 'layout.txt').read_text().splitlines())
