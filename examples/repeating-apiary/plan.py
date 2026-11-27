"""Build a seven-row apiary and independently replay its gate-to-gate collection walk."""

import argparse
from collections import Counter, deque
from pathlib import Path


STEPS = ((1, 0), (0, 1), (-1, 0), (0, -1))
GATE = (0, 1)


def neighbors(tile):
    x, y = tile
    return {(x + dx, y + dy) for dx, dy in STEPS}


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def crow_covers(a, b):
    # A conservative subset of the ordinary scarecrow's area.
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= 64


def nursery(width, priority):
    if (width - 2) % 7 == 0 and priority == 'sprinklers':
        spr = set(range(4, width - 4, 7))
        return {s + d for s in spr for d in (-1, 1)}, spr

    # State records the distance to the last flower, the most recent tile,
    # and whether a flower just planted still needs water from its right.
    initial = (5, '.', False)
    scores = {initial: (0, 0)}
    parents = []
    for x in range(3, width - 3):
        next_scores = {}
        previous = {}
        choices = ('F',) if x in (3, width - 4) else ('F', 'S', '.')
        for state, score in scores.items():
            gap, last, needs_right = state
            for mark in choices:
                if needs_right and mark != 'S':
                    continue
                if mark == 'F':
                    if last == 'F':
                        continue
                    new_state = (0, mark, last != 'S')
                else:
                    if gap >= 4:
                        continue
                    new_state = (gap + 1, mark, False)
                added = (int(mark == 'S'), int(mark == 'F'))
                if priority == 'flowers':
                    added = added[::-1]
                new_score = (score[0] + added[0], score[1] + added[1])
                if new_state not in next_scores or new_score < next_scores[new_state]:
                    next_scores[new_state] = new_score
                    previous[new_state] = state
        parents.append(previous)
        scores = next_scores

    # The right edge is a house, so the last flower must already have water.
    end = (0, 'F', False)
    if end not in scores:
        raise ValueError('no nursery fits this width')
    flowers, sprinklers = set(), set()
    for i in range(len(parents) - 1, -1, -1):
        if end[1] == 'F':
            flowers.add(i + 3)
        elif end[1] == 'S':
            sprinklers.add(i + 3)
        end = parents[i][end]
    return flowers, sprinklers


def solve_nursery(width, priority):
    """Independent CP-SAT certification of the two resource counts."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    bed = range(3, width - 3)
    rose = {x: model.new_bool_var(f'flower_{x}') for x in bed}
    spr = {x: model.new_bool_var(f'sprinkler_{x}') for x in bed}
    for x in bed:
        model.add(rose[x] + spr[x] <= 1)
        model.add(rose[x] <= spr.get(x - 1, 0) + spr.get(x + 1, 0))
        if x + 1 in rose:
            model.add(rose[x] + rose[x + 1] <= 1)
    # The end flowers cover the left and right outer houses. All the
    # top-row houses must be within two horizontal tiles of a flower.
    model.add(rose[3] == 1)
    model.add(rose[width - 4] == 1)
    for x in range(1, width - 1):
        model.add_bool_or([rose[b] for b in range(x - 2, x + 3) if b in rose])

    first, second = (spr, rose) if priority == 'sprinklers' else (rose, spr)
    model.minimize((width + 1) * sum(first.values()) + sum(second.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    if solver.solve(model) != cp_model.OPTIMAL:
        raise ValueError('no nursery fits this width')
    return {x for x in bed if solver.value(rose[x])}, {x for x in bed if solver.value(spr[x])}


def build(width, priority):
    if width < 9:
        raise ValueError('a permanently watered build needs a width of at least nine')
    cells = {(x, y): '.' for x in range(width) for y in range(7)}
    lap = {(x, y) for x in range(1, width - 1) for y in range(1, 6)
           if x in (1, width - 2) or y in (1, 5)}
    for cell in lap:
        cells[cell] = '+'
    for cell in set().union(*(neighbors(p) for p in lap)) - lap:
        cells[cell] = 'H'
    cells[GATE] = 'G'

    flowers, sprinklers = nursery(width, priority)
    for x in flowers:
        cells[x, 3] = 'F'
    for x in sprinklers:
        cells[x, 3] = 'S'
    for x in flowers:
        for side in (x - 1, x + 1):
            if cells[side, 3] == '.':
                cells[side, 3] = 'C'

    # Some short nurseries are already entirely shielded by their houses and
    # sprinklers. Use a spare tile for the crop-protection scarecrow.
    crowns = {p for p, mark in cells.items() if mark == 'C'}
    uncovered = {(x, 3) for x in flowers if not any(crow_covers((x, 3), c) for c in crowns)}
    while uncovered:
        free = sorted((p for p in cells if cells[p] == '.'), key=lambda p: (p[1], p[0]))
        best = max(free, key=lambda p: sum(crow_covers(p, f) for f in uncovered))
        covered = {f for f in uncovered if crow_covers(best, f)}
        if not covered:
            raise ValueError('no available scarecrow site')
        cells[best] = 'C'
        uncovered -= covered
    return [''.join(cells[x, y] for x in range(width)) for y in range(7)]


def verify(rows):
    if len(rows) != 7 or len(rows[0]) < 9 or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError('expected a rectangle seven tiles high and at least nine tiles wide')
    width = len(rows[0])
    cells = {(x, y): c for y, row in enumerate(rows) for x, c in enumerate(row)}
    if set(cells.values()) - set('HFC+GS.'):
        raise ValueError('unknown tile symbol')
    sites = {c: {p for p in cells if cells[p] == c} for c in 'HFC+GS.'}
    if sites['G'] != {GATE}:
        raise ValueError('expected one gate in the second row at the west edge')

    # Derive the itinerary independently of the ring constructor.
    moves = [(1, 0)] + [(1, 0)] * (width - 3) + [(0, 1)] * 4
    moves += [(-1, 0)] * (width - 3) + [(0, -1)] * 4 + [(-1, 0)]
    pos = GATE
    stops = [pos]
    for dx, dy in moves:
        pos = (pos[0] + dx, pos[1] + dy)
        if cells.get(pos) not in ('G', '+'):
            raise ValueError(f'obstructed step at {pos}')
        stops.append(pos)
    loop = set(stops[1:-1])
    if pos != GATE or loop != sites['+'] or len(loop) != 2 * width + 2:
        raise ValueError('the route must make one simple lap and return to the gate')
    if len(sites['H']) != 2 * len(loop) - 5:
        raise ValueError('house count does not attain the closed-walk bound')
    for p in sites['H']:
        if not neighbors(p) & loop:
            raise ValueError(f'no side pickup on the lap at {p}')
        if not any(distance(p, f) <= 5 for f in sites['F']):
            raise ValueError(f'no eligible flower at {p}')

    for x, y in sites['F']:
        if not neighbors((x, y)) & sites['S']:
            raise ValueError(f'unwatered flower at {(x, y)}')
        if not any(crow_covers((x, y), c) for c in sites['C']):
            raise ValueError(f'flower outside scarecrow coverage at {(x, y)}')
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (dx or dy) and cells.get((x + dx, y + dy)) not in ('H', 'S', 'C'):
                    raise ValueError(f'open side or diagonal next to flower at {(x, y)}')

    # Soil-grown flowers are walkable in game. Let the flood fill step on any
    # it can reach to check that the physical barriers really isolate them.
    reached = {GATE}
    queue = deque(reached)
    while queue:
        fresh = {p for p in neighbors(queue.popleft()) - reached if cells.get(p) in ('.', '+', 'G', 'F')}
        reached |= fresh
        queue.extend(fresh)
    if not loop <= reached or reached & sites['F']:
        raise ValueError('an inaccessible lap or an exposed flower')
    counts = Counter(cells.values())
    return (f"{width}×7 | {counts['H']} houses | {counts['F']} flowers | "
            f"{counts['S']} basic sprinkler{'s' if counts['S'] != 1 else ''} | "
            f"{counts['C']} scarecrow{'s' if counts['C'] != 1 else ''} | "
            f"{len(loop)} lap steps | {len(moves)} steps from and back to the gate")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, help='plot width in tiles (default 9)')
    parser.add_argument('--priority', choices=['sprinklers', 'flowers'], default='sprinklers',
                        help='minimize this resource first and the other resource second')
    parser.add_argument('--solve', action='store_true',
                        help='also prove the generated nursery resource counts with CP-SAT')
    parser.add_argument('--check', type=Path, help='replay a saved plan instead of generating one')
    options = parser.parse_args()
    if options.check and (options.width or options.solve):
        parser.error('choose either --width or --check')
    if options.width is not None and options.width < 9:
        parser.error('--width must be at least nine')
    plan = (options.check.read_text().splitlines() if options.check
            else build(options.width or 9, options.priority))
    if options.solve:
        roses, sprays = solve_nursery(options.width or 9, options.priority)
        counts = Counter(''.join(plan))
        if (len(roses), len(sprays)) != (counts['F'], counts['S']):
            raise ValueError('independent nursery optima disagree')
        print('CP-SAT proved the nursery resource counts.')
    print(verify(plan))
    print('\n'.join(plan))
