"""Shortest closed walk that passes a pickup tile for every item on a fixed layout."""
from collections import defaultdict
from itertools import groupby

from ortools.sat.python import cp_model

from island_route import DIRECTIONS

STEPS = ((1, 0), (0, 1))


def shortest_closed_walk(start, ground, pickups, seconds=60, workers=8):
    """Return (walk, proven). `pickups` maps each item to the tiles it can be collected from.

    A closed walk is a connected set of grid edges, each used once or twice, with an
    even number of uses at every tile. Each visited tile records its distance from the
    entrance along used edges, which keeps the walk in one piece.
    """
    ground = set(ground)
    options = {item: set(stand) & ground for item, stand in pickups.items()}
    if start not in ground or not all(options.values()):
        raise ValueError('an item has no reachable pickup tile')
    model = cp_model.CpModel()
    once, twice, ends = {}, {}, defaultdict(list)
    for p in sorted(ground):
        for dx, dy in STEPS:
            q = (p[0] + dx, p[1] + dy)
            if q in ground:
                once[p, q] = model.new_bool_var('once')
                twice[p, q] = model.new_bool_var('twice')
                model.add_implication(twice[p, q], once[p, q])
                ends[p].append((q, (p, q)))
                ends[q].append((p, (p, q)))
    visit = {p: model.new_bool_var('visit') for p in sorted(ground)}
    depth = {p: model.new_int_var(0, len(ground), 'depth') for p in sorted(ground)}
    model.add(visit[start] == 1)
    model.add(depth[start] == 0)
    for p in sorted(ground):
        half = model.new_int_var(0, 4, 'half')
        model.add(sum(once[e] + twice[e] for _, e in ends[p]) == 2 * half)
        model.add(half >= 1).only_enforce_if(visit[p])
        model.add(half == 0).only_enforce_if(~visit[p])
        if p == start:
            continue
        model.add(depth[p] == 0).only_enforce_if(~visit[p])
        parents = []
        for q, e in ends[p]:
            parent = model.new_bool_var('parent')
            model.add_implication(parent, once[e])
            # Depth is the distance from the entrance along used edges, which leaves
            # one labeling per walk: tiles joined by a used edge differ by at most one.
            model.add(depth[p] == depth[q] + 1).only_enforce_if(parent)
            model.add(depth[p] <= depth[q] + 1).only_enforce_if(once[e])
            parents.append(parent)
        model.add_exactly_one([~visit[p], *parents])
    for stand in options.values():
        if start not in stand:
            model.add_bool_or(visit[p] for p in sorted(stand))
    model.minimize(sum(once.values()) + sum(twice.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = workers
    solver.parameters.max_time_in_seconds = seconds
    # These three searches work on the lower bound. Spare workers shorten the walk.
    solver.parameters.subsolvers.extend(['core', 'lb_tree_search', 'objective_lb_search'])
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError('walk search needs more time')
    # Walk the edges once each (Hierholzer), starting and finishing at the entrance.
    spare = defaultdict(list)
    for (a, b), var in once.items():
        n = solver.value(var) + solver.value(twice[a, b])
        spare[a] += [b] * n
        spare[b] += [a] * n
    stack, walk = [start], []
    while stack:
        here = stack[-1]
        if spare[here]:
            nxt = spare[here].pop()
            spare[nxt].remove(here)
            stack.append(nxt)
        else:
            walk.append(stack.pop())
    walk.reverse()
    check_walk(start, ground, options, walk)
    return walk, status == cp_model.OPTIMAL


def check_walk(start, ground, pickups, walk):
    """Replay a walk one tile step at a time."""
    if not walk or walk[0] != start or walk[-1] != start:
        raise ValueError('walk must start and finish at the entrance')
    if set(walk) - set(ground):
        raise ValueError('walk leaves the open floor')
    if any(abs(a[0]-b[0]) + abs(a[1]-b[1]) != 1 for a, b in zip(walk, walk[1:])):
        raise ValueError('walk contains a step that is not to a neighboring tile')
    visited = set(walk)
    for item, stand in pickups.items():
        if not visited & set(stand):
            raise ValueError(f'walk misses the item at {item}')


def tokens(walk):
    """Compass directions and tile counts, as in the saved walk files."""
    moves = (DIRECTIONS[b[0]-a[0], b[1]-a[1]] for a, b in zip(walk, walk[1:]))
    return ' '.join(d + str(len(list(run))) for d, run in groupby(moves))
