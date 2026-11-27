"""Jointly improve protected house placement and a closed harvest walk on the west bank."""
import argparse
import random
import sys
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from island import Island, read_grid, supports
from island_route import DIRECTIONS, check_walk, read_walk


def edge(a, b):
    return (a, b) if a < b else (b, a)


def trace(entrance, crossings):
    """Recover an actual walk through the connected, even-degree multigraph."""
    neighbors = defaultdict(list)
    for (a, b), count in sorted(crossings.items()):
        neighbors[a].extend([b] * count)
        neighbors[b].extend([a] * count)
    stack = [entrance]
    result = []
    while stack:
        a = stack[-1]
        if neighbors[a]:
            b = neighbors[a].pop()
            neighbors[b].remove(a)
            stack.append(b)
        else:
            result.append(stack.pop())
    if len(result) != 1 + sum(crossings.values()):
        raise ValueError('the route contains disconnected edges')
    return result[::-1]


def contract(crossings):
    neighbors = defaultdict(set)
    degrees = Counter()
    for (a, b), count in crossings.items():
        neighbors[a].add(b)
        neighbors[b].add(a)
        degrees[a] += count
        degrees[b] += count
    zone = {}
    for start in sorted(neighbors):
        if start in zone:
            continue
        queue = [start]
        zone[start] = start
        for p in queue:
            for n in neighbors[p]:
                if n not in zone:
                    zone[n] = start
                    queue.append(n)
    return zone, degrees


def improve(board, houses, flowers, crossings, patch, args):
    model = cp_model.CpModel()
    fixed_h, fixed_f = houses - patch, flowers - patch
    build = patch & board.build
    hive = {p: model.new_bool_var('house') for p in sorted(build)}
    rose = {p: model.new_bool_var('rose') for p in sorted(build & board.beds - board.edge_beds)}
    empty = {p: model.new_bool_var('empty') for p in sorted(build)}
    for p in build:
        model.add_exactly_one([hive[p], empty[p]] + ([rose[p]] if p in rose else []))
        model.add_hint(hive[p], p in houses)
        model.add_hint(empty[p], p not in houses | flowers)
        if p in rose:
            model.add_hint(rose[p], p in flowers)
    pots = sum(r for p, r in rose.items() if board.base[p] == 'P')
    model.add(pots <= args.pots - board.pots(fixed_f))
    model.add(sum(rose.values()) <= args.roses - len(fixed_f))
    fixed_empty = board.floor - build - fixed_h - fixed_f
    for p in fixed_f | rose.keys():
        if p in rose and board.around[p] & fixed_empty:
            model.add(rose[p] == 0)
            continue
        for n in board.around[p] & build:
            if p in rose:
                model.add_at_most_one(rose[p], empty[n])
            else:
                model.add(empty[n] == 0)

    free = board.floor - fixed_h - fixed_f
    local = {edge(p, q) for p in patch for q in board.sides[p] & free}
    fixed_edges = {e: count for e, count in crossings.items() if e not in local}
    zone, fixed_degree = contract(fixed_edges)
    count = {}
    active = {}
    incident = defaultdict(list)
    for a, b in sorted(local):
        e = (a, b)
        count[e] = model.new_int_var(0, 1 if args.one_lap else 2, 'crossings')
        active[e] = model.new_bool_var('edge used')
        model.add(count[e] >= active[e])
        model.add(count[e] <= 2 * active[e])
        model.add_hint(count[e], crossings.get(e, 0))
        model.add_hint(active[e], e in crossings)
        incident[a].append(count[e])
        incident[b].append(count[e])

    visited = {p: True for p in fixed_degree}
    old_visits = {p for e in crossings for p in e}
    repeats = []
    for p, edges in incident.items():
        if p == board.start or fixed_degree[p]:
            visited[p] = True
        else:
            visited[p] = model.new_bool_var('visited')
            model.add_hint(visited[p], p in old_visits)
        degree = len(board.sides[p])
        arrivals = model.new_int_var(0, degree, 'arrivals')
        model.add(2 * arrivals == fixed_degree[p] + sum(edges))
        model.add(visited[p] <= arrivals)
        model.add(arrivals <= (1 if args.one_lap else degree) * visited[p])
        if p in empty:
            model.add(empty[p] >= visited[p])
        repeats.append(arrivals - visited[p])

    # Every used component must have a chain of used edges back to the entrance.
    root = zone.get(board.start, board.start)
    always_on = set(zone.values()) | {root}
    nodes = always_on | {zone.get(p, p) for p in incident}
    depth = {n: model.new_int_var(0, len(nodes), 'depth') for n in nodes}
    model.add(depth[root] == 0)
    parents = defaultdict(list)
    for (a, b), used in active.items():
        a, b = zone.get(a, a), zone.get(b, b)
        if a == b:
            continue
        for child, parent in ((a, b), (b, a)):
            if child == root:
                continue
            choose = model.new_bool_var('parent')
            model.add_implication(choose, used)
            model.add(depth[parent] < depth[child]).only_enforce_if(choose)
            parents[child].append(choose)
    for p in nodes - {root}:
        supports(model, True if p in always_on else visited[p], parents[p])
    for p in fixed_h | build:
        has_house = hive.get(p, True)
        if not board.blooms[p] & fixed_f:
            supports(model, has_house, (rose[n] for n in board.blooms[p] & rose.keys()))
        supports(model, has_house, (visited[n] for n in board.stands[p] & visited.keys()))

    model.add(sum(hive.values()) >= min(args.min_houses, len(houses)) - len(fixed_h))
    score = args.house_weight * sum(hive.values()) - sum(count.values()) - args.repeat_penalty * sum(repeats)
    pot_weight = args.roses + 1
    model.maximize((args.pots + 1) * pot_weight * score - pot_weight * pots - sum(rose.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = args.workers
    solver.parameters.max_time_in_seconds = args.seconds
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return houses, flowers, crossings
    return (fixed_h | {p for p, v in hive.items() if solver.value(v)},
            fixed_f | {p for p, v in rose.items() if solver.value(v)},
            fixed_edges | {e: solver.value(v) for e, v in count.items() if solver.value(v)})


def score(board, houses, flowers, crossings, args):
    length = sum(crossings.values())
    repeated = length - len({p for e in crossings for p in e})
    return (args.house_weight * len(houses) - length - args.repeat_penalty * repeated,
            -board.pots(flowers), -len(flowers))


def save(board, houses, flowers, walk, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'layout.txt').write_text('\n'.join(board.grid(houses, flowers)) + '\n')
    moves = [DIRECTIONS[b[0]-a[0], b[1]-a[1]] for a, b in zip(walk, walk[1:])]
    words = [direction + str(len(list(run))) for direction, run in groupby(moves)]
    (directory / 'walk.txt').write_text('\n'.join(' '.join(words[i:i+16]) for i in range(0, len(words), 16)) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('walk', type=Path)
    parser.add_argument('output', type=Path, help='directory for the best layout.txt and walk.txt')
    parser.add_argument('--side-only', action='store_true')
    parser.add_argument('--one-lap', action='store_true', help='preserve a simple cycle in the starting walk')
    parser.add_argument('--house-weight', type=int, default=4, help='steps a new house is worth in the search')
    parser.add_argument('--repeat-penalty', type=int, default=1, help='extra cost per repeated standing tile')
    parser.add_argument('--min-houses', type=int, default=0, help='preserve this many houses once reached')
    parser.add_argument('--pots', type=int, help='pot budget, defaults to the starting layout')
    parser.add_argument('--roses', type=int, help='rose budget, defaults to the starting layout')
    parser.add_argument('--seed', type=int, default=54)
    parser.add_argument('--passes', type=int, default=4)
    parser.add_argument('--seconds', type=float, default=.5, help='CP-SAT time limit per patch')
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    board = Island(read_grid(ROOT / 'examples/ginger-island/terrain.txt'), side_only=args.side_only)
    houses, flowers = board.decode(read_grid(args.layout))
    board.verify(houses, flowers)
    if flowers & board.edge_beds:
        parser.error('the starting layout must shelter its roses from the survey boundary')
    walk = read_walk(board.start, args.walk.read_text())
    check_walk(board, houses, flowers, walk)
    if len(walk) < 3 or (args.one_lap and (len(walk) < 5 or len(set(walk)) != len(walk)-1)):
        parser.error('supply a closed nonempty walk, with unique standing tiles for --one-lap')
    # Dropping two surplus traversals preserves even degrees and connected support.
    multiplicity = Counter(edge(a, b) for a, b in zip(walk, walk[1:]))
    crossings = {e: 1 + (n-1) % 2 for e, n in multiplicity.items()}
    if args.pots is None:
        args.pots = board.pots(flowers)
    if args.roses is None:
        args.roses = len(flowers)
    if args.pots < board.pots(flowers) or args.roses < len(flowers):
        parser.error('starting plantings must fit the given budgets')
    rng = random.Random(args.seed)
    save(board, houses, flowers, trace(board.start, crossings), args.output)
    for sweep in range(args.passes):
        width, height = rng.choice([(7, 9), (9, 7), (8, 8), (10, 7), (7, 10), (11, 8), (8, 11)])
        dx, dy = width-2, height-2
        x0, y0 = -rng.randrange(dx), -rng.randrange(dy)
        origins = [(x, y) for x in range(x0, max(map(len, board.rows)), dx)
                   for y in range(y0, len(board.rows), dy)]
        rng.shuffle(origins)
        for x, y in origins:
            patch = {p for p in board.floor if x <= p[0] < x+width and y <= p[1] < y+height}
            if not patch:
                continue
            candidate = improve(board, houses, flowers, crossings, patch, args)
            if candidate == (houses, flowers, crossings):
                continue
            if score(board, *candidate, args) < score(board, houses, flowers, crossings, args):
                continue
            new_h, new_f, new_edges = candidate
            # A lap may skip a bridge entrance. The entrance still needs an open approach.
            if not board.entries <= board.flood(board.start, board.floor - new_h - new_f):
                continue
            board.verify(new_h, new_f)
            walk = trace(board.start, new_edges)
            check_walk(board, new_h, new_f, walk)
            if args.one_lap and len(set(walk)) != len(walk)-1:
                raise ValueError('walk repeats a standing tile')
            save(board, new_h, new_f, walk, args.output)
            houses, flowers, crossings = candidate
        print(f'Pass {sweep+1} found {len(houses)} houses in {sum(crossings.values())} steps.')


if __name__ == '__main__':
    main()
