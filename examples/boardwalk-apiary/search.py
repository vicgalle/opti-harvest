"""Minimize the flowers in a boardwalk or pack boardwalks onto a farm survey."""
import argparse
import random

from ortools.sat.python import cp_model

from plan import Pier, Terrain, build, read_templates


def solve_flowers(templates):
    for length, rows in templates.items():
        cells = Pier(0, 0, length, False).cells(templates)
        lane = {p for p, c in cells.items() if c == '+'}
        beds = [p for p, c in cells.items() if c in 'F.'
                and all(max(abs(p[0]-x), abs(p[1]-y)) > 1 for x, y in lane)]
        model = cp_model.CpModel()
        rose = {p: model.new_bool_var(f'rose{p}') for p in beds}
        for (x, y), mark in cells.items():
            if mark == 'H':
                model.add_bool_or(v for (a, b), v in rose.items() if abs(x-a)+abs(y-b) <= 5)
        model.minimize(sum(rose.values()))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        if solver.solve(model) != cp_model.OPTIMAL:
            raise RuntimeError('flower minimum unresolved')
        used = [p for p, v in rose.items() if solver.value(v)]
        print(f'{length}×{len(rows)}: minimum {len(used)} flowers, e.g. {used}')


def row_starts(row, width, legal):
    """Bit x is set if width consecutive tiles starting at x are all legal."""
    starts = run = 0
    for x, char in enumerate(row):
        run = run + 1 if char in legal else 0
        if run >= width:
            starts |= 1 << (x-width+1)
    return starts


def candidates(terrain, templates):
    sites, masks = [], []
    stride = len(terrain.rows[0])
    for length in sorted(templates, reverse=True):
        for vertical in (False, True):
            w, h = (7, length) if vertical else (length, 7)
            beds = [p for p, c in Pier(0, 0, length, vertical).cells(templates).items() if c == 'F']
            buildable = [row_starts(r, w, 'P.') for r in terrain.rows]
            rim = [row_starts(r, w+2, 'P.WE') << 1 for r in terrain.rows]
            # Pad just the east and south edges. Disjoint padded masks leave one
            # shared walking tile between neighboring rectangles in either order.
            padded = sum(((1 << (w+1))-1) << (stride*j) for j in range(h+1))
            for y in range(1, len(terrain.rows)-h):
                starts = buildable[y]
                for allowed in buildable[y+1:y+h] + rim[y-1:y+h+1]:
                    starts &= allowed
                while starts:
                    bit = starts & -starts
                    starts -= bit
                    x = bit.bit_length()-1
                    if all((x+a, y+b) in terrain.soil for a, b in beds):
                        sites.append(Pier(x, y, length, vertical))
                        masks.append(padded << (stride*y+x))
    return sites, masks


def sample_packings(sites, masks, samples):
    rng = random.Random(11)
    pool, best = set(), []
    best_score = 0
    for _ in range(samples):
        sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
        offset_x, offset_y = rng.randrange(8), rng.randrange(8)
        prefer_vertical = rng.randrange(2)
        slope = rng.choice((0.06, 0.12, 0.35, 0.75, 1.5, 4))
        noise = rng.choice((0, 1, 5, 9))
        turn = rng.choice((0, 0, 8, 14, 25))
        align = rng.choice((0, 4, 12, 24))

        def priority(i):
            p = sites[i]
            off_grid = (p.x-offset_x if p.vertical else p.y-offset_y) % 8 != 0
            return (p.length == 10, sign_x*p.x + sign_y*p.y*slope + rng.random()*noise
                    + (p.vertical != prefer_vertical)*turn + off_grid*align)

        packed, occupied = [], 0
        for i in sorted(range(len(sites)), key=priority):
            if not occupied & masks[i]:
                packed.append(i)
                occupied |= masks[i]
        score = sum(3 if sites[i].length == 29 else 1 for i in packed)
        if score > best_score:
            best_score, best = score, packed
        if score >= best_score-7:
            pool.update(packed)
    return sorted(pool), best


def pack(terrain, templates, samples, seconds):
    sites, masks = candidates(terrain, templates)
    pool, best = sample_packings(sites, masks, samples)
    model = cp_model.CpModel()
    use = {i: model.new_bool_var(f'use{i}') for i in pool}
    sharing = {}
    for i in pool:
        p = sites[i]
        for u in range(p.length+1):
            for v in range(8):
                sharing.setdefault(p.tile(u, v), []).append(i)
    # Thousands of tile cliques have the exact same member list.
    for members in set(tuple(group) for group in sharing.values() if len(group) > 1):
        model.add_at_most_one(use[i] for i in members)
    selected = set(best)
    for i, var in use.items():
        model.add_hint(var, i in selected)
    model.maximize(sum((3 if sites[i].length == 29 else 1)*var for i, var in use.items()))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 6
    solver.parameters.max_time_in_seconds = seconds
    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and solver.objective_value >= sum(
            3 if sites[i].length == 29 else 1 for i in best):
        selected = {i for i, v in use.items() if solver.value(v)}
    return [sites[i] for i in sorted(selected)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=('flowers', 'beach', 'everfarm'))
    parser.add_argument('--samples', type=int, default=190)
    parser.add_argument('--seconds', type=float, default=54, help='CP-SAT time after sampling')
    args = parser.parse_args()
    if args.samples < 1 or args.seconds <= 0:
        parser.error('samples and seconds must be positive')
    templates = read_templates()
    if args.task == 'flowers':
        solve_flowers(templates)
        return
    terrain = Terrain(args.task)
    packed = pack(terrain, templates, args.samples, args.seconds)
    sites = {f'P{i:02}': p for i, p in enumerate(packed, 1)}
    marks = build(terrain, templates, sites)
    print(f'# {sum(c == "H" for c in marks.values())} houses, {len(sites)} boardwalks')
    for label, p in sites.items():
        print(label, p.x, p.y, p.length, 'V' if p.vertical else 'H')


if __name__ == '__main__':
    main()
