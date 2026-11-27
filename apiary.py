"""Maximize collectible flower-honey bee houses on a rectangular plot."""
import argparse
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from itertools import product

from ortools.sat.python import cp_model

Cell = tuple[int, int]
STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
AROUND = tuple(p for p in product(range(-1, 2), repeat=2) if p != (0, 0))
BLOOM = tuple((x, y) for x, y in product(range(-5, 6), repeat=2) if 0 < abs(x) + abs(y) <= 5)


def neighbors(cell, offsets):
    x, y = cell
    return ((x + dx, y + dy) for dx, dy in offsets)


@dataclass(frozen=True)
class Plot:
    width: int
    height: int
    collection: int = 8
    entrance: Cell | None = None
    solid_flowers: bool = False
    center_only: bool = False
    max_flowers: int | None = None

    def __post_init__(self):
        if min(self.width, self.height) < 1 or self.collection not in (4, 8):
            raise ValueError("dimensions must be positive and collection must be 4 or 8")
        if self.max_flowers is not None and self.max_flowers < int(self.center_only):
            raise ValueError("flower budget is too small")
        if self.entrance is not None:
            # JSON coordinates arrive as lists. Keep the tile usable as a graph key.
            object.__setattr__(self, "entrance", tuple(self.entrance))
            x, y = self.entrance
            if not (0 <= x < self.width and 0 <= y < self.height and
                    (x in (0, self.width - 1) or y in (0, self.height - 1))):
                raise ValueError("entrance must be a tile on the plot boundary")
            if self.center_only and self.entrance == self.center:
                raise ValueError("the reserved entrance cannot contain the center flower")

    @property
    def center(self):
        return self.width // 2, self.height // 2

    @property
    def cells(self):
        return set(product(range(self.width), range(self.height)))

    @property
    def reach(self):
        return AROUND if self.collection == 8 else STEPS


def check_layout(plot, rows):
    """Independent verifier. Flood the physical plot from its actual entrance(s)."""
    if len(rows) != plot.height or any(len(row) != plot.width for row in rows):
        raise ValueError("layout dimensions differ from the plot")
    if any(set(row) - set("HF.") for row in rows):
        raise ValueError("unknown tile")
    houses = {(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == 'H'}
    flowers = {(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == 'F'}
    if plot.center_only and flowers != {plot.center}:
        raise ValueError("expected a single center flower")
    if plot.max_flowers is not None and len(flowers) > plot.max_flowers:
        raise ValueError("too many flowers")
    walkable = plot.cells - houses
    if plot.solid_flowers:
        walkable -= flowers
    if plot.entrance is None:
        # This entire exterior ring is connected by cardinal moves.
        starts = {(x, y) for x in range(-1, plot.width + 1) for y in (-1, plot.height)}
        starts |= {(x, y) for x in (-1, plot.width) for y in range(plot.height)}
    else:
        x, y = plot.entrance
        if rows[y][x] != '.':
            raise ValueError("the entrance must be clear")
        starts = {plot.entrance}
    seen = starts.copy()
    queue = deque(starts)
    while queue:
        x, y = queue.popleft()
        for n in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            if n in walkable and n not in seen:
                seen.add(n)
                queue.append(n)
    for x, y in houses:
        if not any(abs(x-a) + abs(y-b) <= 5 for a, b in flowers):
            raise ValueError(f"no flower in range of {(x, y)}")
        if not any((x+dx, y+dy) in seen for dx, dy in plot.reach):
            raise ValueError(f"cannot collect from {(x, y)}")


def draw(plot, houses, flowers):
    return [''.join('H' if (x, y) in houses else 'F' if (x, y) in flowers else '.'
                    for x in range(plot.width)) for y in range(plot.height)]


def choose_flowers(houses, candidates, limit=None):
    """Greedy set cover, followed by removal of redundant flowers."""
    missing = set(houses)
    coverage = {c: houses.intersection(neighbors(c, BLOOM)) for c in sorted(candidates)}
    selected = []
    while missing and coverage and (limit is None or len(selected) < limit):
        best = max(coverage, key=lambda c: len(coverage[c] & missing))
        gain = missing.intersection(coverage.pop(best))
        if not gain:
            break
        missing -= gain
        selected.append(best)
    covered = houses - missing
    for c in selected.copy():
        others = set(selected) - {c}
        if all(any(n in others for n in neighbors(h, BLOOM))
               for h in covered.intersection(neighbors(c, BLOOM))):
            selected.remove(c)
    return covered, set(selected)


def stripe_paths(width, height):
    """Stems from the top cover triples of interior columns; right stubs cover the rest."""
    inner_w, inner_h = max(0, width - 2), max(0, height - 2)
    paths = {(2 + 3*k, y) for k in range(inner_w // 3) for y in range(inner_h)}
    remaining = inner_w % 3
    for first in range(1, inner_h + 1, 3):
        y = min(first + 1, inner_h)
        paths.update((width - 1 - i, y) for i in range(remaining))
    return paths


def gate_paths(width, height, entrance):
    """Connected vertical lanes. Alternate top and bottom links to cover the turns."""
    x_gate, y_gate = entrance
    xs = [min(x + 1, width - 2) for x in range(0, width, 3)]
    paths = {(x, y) for x in xs for y in range(1, height - 1)}
    for i, (left, right) in enumerate(zip(xs, xs[1:])):
        y = 1 if i % 2 == 0 else height - 2
        paths.update((x, y) for x in range(left + 1, right))
    paths.update({(0, y_gate), (1, y_gate)})
    if x_gate == width - 1:
        paths = {(width - 1 - x, y) for x, y in paths}
    return paths


def candidate_paths(plot):
    for transpose in (False, True):
        w, h = (plot.height, plot.width) if transpose else (plot.width, plot.height)
        gate = plot.entrance
        if transpose and gate is not None:
            gate = gate[::-1]
        if gate and plot.collection == 8 and min(w, h) >= 3:
            if gate[0] not in (0, w - 1):
                continue
            paths = gate_paths(w, h, gate)
        else:
            if plot.collection == 8:
                paths = stripe_paths(w, h)
            else:
                paths = {(x, y) for x in range(1, w, 3) for y in range(h)}
                if w % 3 == 1:
                    paths.update((w - 1, y) for y in range(h))
            if gate:
                paths.update((x, y) for x in range(w) for y in (0, h - 1))
                paths.update((x, y) for x in (0, w - 1) for y in range(h))
        yield {(y, x) for x, y in paths} if transpose else paths


def seed_layout(plot):
    """Construct a feasible lower bound before exact search, including for short timeouts."""
    cells = plot.cells
    best = (set(), {plot.center} if plot.center_only else set())
    for paths in candidate_paths(plot):
        candidates = cells - paths
        if plot.center_only:
            flowers = {plot.center}
            houses = candidates.intersection(neighbors(plot.center, BLOOM))
        else:
            # Put the first flowers on reserved paths whenever walking on crops is allowed.
            allowed = (cells - paths) if plot.solid_flowers else paths
            if plot.entrance is not None:
                allowed = allowed - {plot.entrance}
            houses, flowers = choose_flowers(candidates, allowed, plot.max_flowers)
            # Thin plots can be harvested entirely from outside, and need flowers in the beds.
            if candidates - houses and (plot.max_flowers is None or len(flowers) < plot.max_flowers):
                budget = None if plot.max_flowers is None else plot.max_flowers - len(flowers)
                extra, more = choose_flowers(candidates - houses, candidates - flowers, budget)
                houses |= extra
                flowers |= more
            houses -= flowers
        if len(houses) > len(best[0]):
            try:
                check_layout(plot, draw(plot, houses, flowers))
            except ValueError:
                # Side-only harvesting or a potted center can interrupt a stripe.
                continue
            best = houses, flowers
    return best


def solve(plot, seconds=30, workers=8):
    if not math.isfinite(seconds) or seconds <= 0 or workers < 1:
        raise ValueError("seconds and workers must be positive")
    cells = plot.cells
    active = cells
    if plot.center_only and plot.entrance is None:
        # Outside this diamond all tiles are empty and connected to the exterior.
        active = ({plot.center} | set(neighbors(plot.center, BLOOM))) & cells
    order = sorted(active)
    model = cp_model.CpModel()
    hive = {p: model.new_bool_var(f"H{p}") for p in order}
    flower = {p: model.new_bool_var(f"F{p}") for p in order}
    route = {p: model.new_bool_var(f"R{p}") for p in order}
    depth = {p: model.new_int_var(0, len(active), f"d{p}") for p in order}
    collect_from_exterior = set()
    for p in order:
        model.add_at_most_one(hive[p], flower[p])
        model.add_at_most_one(hive[p], route[p])
        if plot.solid_flowers:
            model.add_at_most_one(flower[p], route[p])
        if plot.center_only:
            model.add(flower[p] == int(p == plot.center))
        model.add_bool_or([~hive[p]] + [flower[n] for n in neighbors(p, BLOOM) if n in active])

        sides = list(neighbors(p, STEPS))
        adjacent = list(neighbors(p, plot.reach))
        if plot.entrance is None and any(n not in active for n in adjacent):
            collect_from_exterior.add(p)
        else:
            model.add_bool_or([~hive[p]] + [route[n] for n in adjacent if n in active])
        root = p == plot.entrance or (plot.entrance is None and any(n not in active for n in sides))
        if root:
            model.add(depth[p] == 0)
        else:
            parents = []
            for n in sides:
                if n in active:
                    parent = model.new_bool_var(f"parent{p}{n}")
                    model.add_implication(parent, route[n])
                    model.add(depth[n] < depth[p]).only_enforce_if(parent)
                    parents.append(parent)
            model.add_bool_or([~route[p], *parents])

    if plot.entrance is not None:
        model.add(route[plot.entrance] == 1)
        model.add(flower[plot.entrance] == 0)
    if plot.max_flowers is not None:
        model.add(sum(flower.values()) <= plot.max_flowers)

    # Each cardinal extension of a connected route adds at most three new cells
    # to its closed collection neighborhood, for either collection stencil.
    if plot.entrance is None:
        interior = len(active) - len(collect_from_exterior)
        needed = (interior + 2) // 3
    else:
        first = 1 + sum(n in active for n in neighbors(plot.entrance, plot.reach))
        needed = 1 + (len(active) - first + 2) // 3
    upper = len(active) - needed
    total = sum(hive.values())
    model.add(total <= upper)
    model.maximize(total)
    houses, flowers = seed_layout(plot)
    for p in order:
        model.add_hint(hive[p], int(p in houses))
        model.add_hint(flower[p], int(p in flowers))
    model.add(total >= len(houses))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = workers
    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        houses = {p for p in order if solver.value(hive[p])}
        flowers = {p for p in order if solver.value(flower[p])}
    elif status != cp_model.UNKNOWN:
        raise RuntimeError(f"unexpected CP-SAT result: {solver.status_name(status)}")
    if status != cp_model.UNKNOWN:
        upper = min(upper, math.floor(solver.best_objective_bound))
    if not plot.center_only:
        # Keep the routes feasible. In soil we may replant anywhere without a hive.
        allowed = flowers if plot.solid_flowers else cells - houses - {plot.entrance}
        covered, sparse = choose_flowers(houses, allowed)
        if covered == houses and len(sparse) <= len(flowers):
            flowers = sparse
    rows = draw(plot, houses, flowers)
    check_layout(plot, rows)
    return dict(plot=asdict(plot), houses=len(houses), upper_bound=upper,
                flowers=len(flowers), optimal=len(houses) == upper,
                solver_status=solver.status_name(status), seconds=round(solver.wall_time, 3),
                rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('width', type=int)
    parser.add_argument('height', type=int)
    parser.add_argument('--collection', choices=(4, 8), type=int, default=8,
                        help='neighboring tiles from which honey can be collected (default 8)')
    parser.add_argument('--entrance', type=int, nargs=2, metavar=('X', 'Y'),
                        help='sole entrance, a reserved border tile, counted inside the plot (zero-based)')
    parser.add_argument('--solid-flowers', action='store_true', help='exclude flowers from walking routes')
    parser.add_argument('--center-only', action='store_true', help='fix exactly one flower at (width//2, height//2)')
    parser.add_argument('--max-flowers', type=int, help='cap flowers and optimize their locations')
    parser.add_argument('--seconds', type=float, default=30, help='CP-SAT wall-time budget (default 30)')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--json', action='store_true', help='emit machine-readable rules, bounds and grid')
    args = parser.parse_args()
    try:
        plot = Plot(args.width, args.height, args.collection,
                    tuple(args.entrance) if args.entrance else None,
                    args.solid_flowers, args.center_only, args.max_flowers)
        result = solve(plot, args.seconds, args.workers)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        label = 'optimal' if result['optimal'] else 'feasible'
        print(f"{result['houses']} bee houses ({label}, upper bound {result['upper_bound']}), "
              f"{result['flowers']} flowers")
        print('H = bee house   F = flower   . = open ground')
        print(*result['rows'], sep='\n')


if __name__ == '__main__':
    main()
