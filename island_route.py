"""Build and verify a closed controller-friendly harvest walk on a fixed island layout."""
import argparse
from collections import deque
from itertools import groupby
from pathlib import Path

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from ortools.sat.python import cp_model

from island import Island, read_grid

DIRECTIONS = {(1, 0): 'E', (-1, 0): 'W', (0, 1): 'S', (0, -1): 'N'}


def shortest_paths(board, start, open_tiles):
    distance, parent = {start: 0}, {}
    q = deque([start])
    while q:
        p = q.popleft()
        for n in sorted(board.sides[p] & open_tiles):
            if n not in distance:
                distance[n] = distance[p] + 1
                parent[n] = p
                q.append(n)
    return distance, parent


def harvest_walk(board, houses, flowers, seconds):
    empty = board.floor - houses - flowers
    ground = board.flood(board.start, empty)
    model = cp_model.CpModel()
    use = {p: model.new_bool_var('stand') for p in sorted(ground)}
    for h in sorted(houses):
        model.add_bool_or(use[p] for p in sorted(board.stands[h] & ground))
    model.add(use[board.start] == 1)
    model.minimize(sum(use.values()))
    cover = cp_model.CpSolver()
    cover.parameters.num_workers = 1
    cover.parameters.max_time_in_seconds = 2
    status = cover.solve(model)
    stops = [board.start] + [p for p in use if p != board.start and
                             (status == cp_model.UNKNOWN or cover.value(use[p]))]
    # Visit the chosen stops by shortest cardinal paths through this exact layout.
    paths = [shortest_paths(board, p, ground) for p in stops]
    distances = [[dist[q] for q in stops] for dist, _ in paths]
    manager = pywrapcp.RoutingIndexManager(len(stops), 1, 0)
    tour = pywrapcp.RoutingModel(manager)
    cost = tour.RegisterTransitMatrix(distances)
    tour.SetArcCostEvaluatorOfAllVehicles(cost)
    config = pywrapcp.DefaultRoutingSearchParameters()
    config.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    config.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    config.time_limit.FromMilliseconds(max(1, int(seconds * 1000)))
    result = tour.SolveWithParameters(config)
    if result is None:
        raise ValueError('route search needs more time')
    walk = [board.start]
    index = tour.Start(0)
    while not tour.IsEnd(index):
        prev = manager.IndexToNode(index)
        index = result.Value(tour.NextVar(index))
        dest = stops[manager.IndexToNode(index)]
        segment = []
        while dest != stops[prev]:
            segment.append(dest)
            dest = paths[prev][1][dest]
        walk.extend(reversed(segment))
    return walk


def check_walk(board, houses, flowers, walk):
    if not walk or walk[0] != board.start or walk[-1] != board.start:
        raise ValueError('walk must start and finish at the specified entrance')
    visited = set(walk)
    if visited - (board.floor - houses - flowers):
        raise ValueError('walk leaves the accessible ground')
    if any(b not in board.sides[a] for a, b in zip(walk, walk[1:])):
        raise ValueError('walk contains a non-cardinal step')
    if any(not (board.stands[h] & visited) for h in houses):
        raise ValueError('walk misses a controller-friendly pickup')


def read_walk(start, text):
    moves = {code: delta for delta, code in DIRECTIONS.items()}
    walk = [start]
    for token in text.split():
        dx, dy = moves[token[0]]
        count = int(token[1:])
        if count < 1:
            raise ValueError('step counts must be positive')
        for _ in range(count):
            x, y = walk[-1]
            walk.append((x+dx, y+dy))
    return walk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('terrain')
    parser.add_argument('layout')
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument('--save', help='write a new walk as compass directions and tile counts')
    task.add_argument('--check', help='replay a previously saved walk')
    parser.add_argument('--seconds', type=float, default=8)
    args = parser.parse_args()
    board = Island(read_grid(args.terrain))
    h, f = board.decode(read_grid(args.layout))
    board.verify(h, f)
    if args.check:
        walk = read_walk(board.start, Path(args.check).read_text())
    else:
        walk = harvest_walk(board, h, f, args.seconds)
    check_walk(board, h, f, walk)
    if args.save:
        moves = [DIRECTIONS[b[0]-a[0], b[1]-a[1]] for a, b in zip(walk, walk[1:])]
        tokens = [direction + str(len(list(run))) for direction, run in groupby(moves)]
        Path(args.save).write_text('\n'.join(' '.join(tokens[i:i+16])
                                             for i in range(0, len(tokens), 16)) + '\n')
    print(f'{len(walk)-1} steps, {len(h)} houses; start and finish at {board.start} (zero-based)')


if __name__ == '__main__':
    main()
