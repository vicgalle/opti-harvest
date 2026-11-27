"""Lower-bound a closed harvest of a chosen number of houses on a fixed layout."""
import argparse
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from island import Island, read_grid


def bridge_blocks(board, ground):
    """Split walkable ground at bridges and orient each bridge away from the entrance."""
    time = {}
    low = {}
    bridges = []

    def visit(tile, parent):
        time[tile] = low[tile] = len(time)
        for other in sorted(board.sides[tile] & ground):
            if other == parent:
                continue
            if other in time:
                low[tile] = min(low[tile], time[other])
            else:
                visit(other, tile)
                low[tile] = min(low[tile], low[other])
                if low[other] > time[tile]:
                    bridges.append((tile, other))

    visit(board.start, None)
    cut = {frozenset(pair) for pair in bridges}
    remaining = ground.copy()
    block = {}
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        queue = [first]
        for tile in queue:
            block[tile] = first
            for other in board.sides[tile] & remaining:
                if frozenset((tile, other)) not in cut:
                    remaining.remove(other)
                    queue.append(other)
    return bridges, block


def necessary_bridges(board, ground, houses, target, bridges, block):
    """Return bridges whose removal leaves fewer than target houses on the entrance side."""
    children = defaultdict(set)
    for a, b in bridges:
        children[block[a]].add(block[b])
    stands = [{block[n] for n in board.stands[p] & ground} for p in houses]
    forced = []
    for a, b in bridges:
        queue = [block[b]]
        for p in queue:
            queue.extend(children[p])
        far_side = set(queue)
        if sum(bool(options - far_side) for options in stands) < target:
            forced.append((a, b))
    return forced


def walk_bound(board, houses, flowers, target, seconds, tighten=False):
    """Relax connectivity within bridge-free blocks, preserving all legal closed walks."""
    if not 1 <= target <= len(houses):
        raise ValueError(f'choose a harvest size between 1 and {len(houses)}')
    if sum(board.start in board.stands[p] for p in houses) >= target:
        return 0, 0
    ground = board.flood(board.start, board.floor - houses - flowers)
    bridges, block = bridge_blocks(board, ground)
    forced = len(necessary_bridges(board, ground, houses, target, bridges, block))
    model = cp_model.CpModel()
    steps = {}
    for a in sorted(ground):
        for b in sorted(board.sides[a] & ground):
            if a < b:
                steps[a, b] = model.new_int_var(0, 2, 'crossings')
    used = {p: model.new_bool_var('visit') for p in sorted(ground)}
    blocks = {p: model.new_bool_var('block') for p in sorted(set(block.values()))}
    for a, b in bridges:
        # Returning to the entrance crosses this bridge again.
        model.add(steps[tuple(sorted((a, b)))] == 2 * blocks[block[b]])
        model.add(blocks[block[b]] <= blocks[block[a]])
    for p in sorted(ground):
        incident = [steps[tuple(sorted((p, n)))] for n in sorted(board.sides[p] & ground)]
        visits = model.new_int_var(0, len(incident), 'visits')
        model.add(sum(incident) == 2 * visits)
        model.add(used[p] <= visits)
        model.add(visits <= len(incident) * used[p])
        model.add(used[p] <= blocks[block[p]])
    model.add(used[board.start] == 1)
    served = []
    for p in sorted(houses):
        standing = [used[q] for q in sorted(board.stands[p] & ground)]
        if target == len(houses):
            model.add_bool_or(standing)
        else:
            collected = model.new_bool_var('collected')
            model.add_bool_or([~collected, *standing])
            served.append(collected)
    if served:
        model.add(sum(served) >= target)
    model.minimize(sum(steps.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    began = time.monotonic()
    lower = 2 * forced
    while time.monotonic() - began < seconds:
        solver.parameters.max_time_in_seconds = max(.001, seconds - time.monotonic() + began)
        result = solver.solve(model)
        if result not in (cp_model.FEASIBLE, cp_model.OPTIMAL, cp_model.UNKNOWN):
            raise ValueError(f'unexpected relaxation result {solver.status_name(result)}')
        # Every closed square-grid walk has even length.
        lower = max(lower, 2 * math.ceil(solver.best_objective_bound / 2 - 1e-8))
        if not tighten or result == cp_model.UNKNOWN:
            break
        adjacent = defaultdict(set)
        for (a, b), crossings in steps.items():
            if solver.value(crossings):
                adjacent[a].add(b)
                adjacent[b].add(a)
        remaining = set(adjacent)
        separated = []
        while remaining:
            component = [remaining.pop()]
            for p in component:
                new = adjacent[p] & remaining
                remaining -= new
                component.extend(new)
            if board.start not in component:
                separated.append(set(component))
        if not separated:
            break
        # A real trip using one of these tiles enters and leaves this component.
        for component in separated:
            active = model.new_bool_var('visits component')
            model.add_max_equality(active, [used[p] for p in component])
            boundary = [steps[tuple(sorted((p, q)))] for p in component
                        for q in (board.sides[p] & ground) - component]
            model.add(sum(boundary) >= 2 * active)
    return lower, forced


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('houses', type=int)
    parser.add_argument('--side-only', action='store_true')
    parser.add_argument('--tighten', action='store_true', help='add cuts for disconnected candidate walks')
    parser.add_argument('--seconds', type=float, default=30)
    args = parser.parse_args()
    board = Island(read_grid(ROOT / 'examples/ginger-island/terrain.txt'), side_only=args.side_only)
    houses, flowers = board.decode(read_grid(args.layout))
    board.verify(houses, flowers)
    lower, forced = walk_bound(board, houses, flowers, args.houses, args.seconds, args.tighten)
    print(f'{forced} individual links must each be crossed in both directions.')
    print(f'Collecting any {args.houses} of {len(houses)} houses takes at least {lower} steps.')


if __name__ == '__main__':
    main()
