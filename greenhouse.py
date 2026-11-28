"""Plant the most trellis crops the greenhouse can hold with every plant still in reach."""
import argparse
from collections import defaultdict
from itertools import product
from pathlib import Path

from ortools.sat.python import cp_model

from apiary import AROUND, STEPS
from closed_walk import check_walk, shortest_closed_walk, tokens
from island import Island, connect_paths, read_grid, supports
from island_route import read_walk

EXAMPLES = Path(__file__).parent / 'examples' / 'hops-greenhouse'
# Where a plant can be, relative to the farmer, and still be harvested. One Iridium
# Scythe swing reaches two tiles in every direction and three tiles up, from the right
# spot on the standing tile.
SCYTHE = tuple(p for p in product(range(-2, 3), repeat=2) if p != (0, 0)) + ((-1, -3), (0, -3), (1, -3))
REACH = {'mouse': AROUND, 'side': STEPS, 'scythe': SCYTHE}
RADIUS = {'@': 3, 'R': 2}   # pressure-nozzle and plain iridium sprinklers
# Saved plan: (reach, hops, sprinkler symbol or None for Deluxe Retaining Soil)
PLANS = {'93-hops': ('mouse', 93, None), '92-hops-sprinklers': ('mouse', 92, '@'),
         '87-hops-side': ('side', 87, None), '112-hops-scythe': ('scythe', 112, None)}
# Saved daily walk: (reach, steps)
WALKS = {'93-hops': ('mouse', 108), '92-hops-sprinklers': ('mouse', 116), '87-hops-side': ('side', 120),
         '112-hops-scythe': ('scythe', 70), '84-hops-short-lap': ('mouse', 66)}


class Greenhouse:
    """Terrain uses S for soil, . for floor, E for the door tile and X for walls.

    A plan adds T for a trellis crop, A for a walkable crop such as ancient fruit,
    and @ or R for a sprinkler. Trellis crops and sprinklers block walking.
    """

    def __init__(self, terrain=None, reach='mouse'):
        self.board = Island(terrain or read_grid(EXAMPLES / 'terrain.txt'))
        self.soil = self.board.beds
        self.reach = reach
        self.stands = {(x, y): {(x - dx, y - dy) for dx, dy in REACH[reach]} & self.board.floor
                       for x, y in self.soil}
        xs, ys = ({p[i] for p in self.soil} for i in (0, 1))
        self.inner = {(x, y) for x, y in self.soil
                      if min(xs) < x < max(xs) and min(ys) < y < max(ys)}

    def decode(self, rows):
        if list(map(len, rows)) != list(map(len, self.board.rows)):
            raise ValueError('plan must match the terrain dimensions')
        found = defaultdict(set)
        for p, base in self.board.base.items():
            ch = rows[p[1]][p[0]]
            if ch != base and not (ch in 'TA' and base == 'S') and not (ch in RADIUS and base in 'S.'):
                raise ValueError(f'cannot place {ch} on {base} at {p}')
            found[ch].add(p)
        return found['T'], found['A'], {p: RADIUS[c] for c in RADIUS for p in found[c]}

    def verify(self, rows):
        """Independent check: flood the open floor from the door, then test water and reach."""
        hops, fruit, sprinklers = self.decode(rows)
        ground = self.board.flood(self.board.start, self.board.floor - hops - sprinklers.keys())
        for x, y in hops | fruit:
            # Without sprinklers the plan relies on Deluxe Retaining Soil, watered once.
            if sprinklers and not any(max(abs(x-a), abs(y-b)) <= r for (a, b), r in sprinklers.items()):
                raise ValueError(f'unwatered crop at {(x, y)}')
        for p in hops:
            if not self.stands[p] & ground:
                raise ValueError(f'no reachable standing tile for the trellis crop at {p}')
        if fruit - ground:
            raise ValueError('a walkable crop is sealed off')
        return hops, fruit, sprinklers, ground

    def solve(self, radius=0, seconds=60, workers=8, tidy=True):
        """Maximize trellis crops. A tidy plan then prefers more watered lane crops
        and fewer sprinklers.

        Returns (plan rows, proven upper bound on trellis crops).
        """
        board, soil = self.board, self.soil
        sites = {p for p in board.build if radius and
                 any(max(abs(p[0]-a), abs(p[1]-b)) <= radius for a, b in soil)}
        model = cp_model.CpModel()
        hop = {p: model.new_bool_var(f'T{p}') for p in sorted(soil)}
        spr = {p: model.new_bool_var(f'S{p}') for p in sorted(sites)}
        fruit, walk = {}, {p: ~v for p, v in spr.items()}
        for p in sorted(soil):
            walk[p] = model.new_bool_var(f'W{p}')
            model.add_exactly_one([hop[p], walk[p]] + ([spr[p]] if radius else []))
        reachable = connect_paths(model, board, soil | sites, set(), walk)
        for (x, y), planted in hop.items():
            supports(model, planted, (reachable[q] for q in self.stands[x, y]))
            # Open soil the farmer can walk to carries a second crop if it is watered.
            fruit[x, y] = model.new_bool_var(f'A{(x, y)}')
            model.add_implication(fruit[x, y], reachable[x, y])
            if radius:
                wet = [v for (a, b), v in spr.items()
                       if (a, b) != (x, y) and max(abs(x-a), abs(y-b)) <= radius]
                model.add_bool_or([~planted, *wet])
                model.add_bool_or([~fruit[x, y], *wet])
        if self.reach != 'scythe':
            # Each step onto a new soil tile brings at most three more inner tiles into reach.
            model.add(sum(hop[p] for p in self.inner) <=
                      3 * sum(walk[p] for p in soil) - sum(walk[p] for p in self.inner))
        total = sum(hop.values())
        weight = 10000 if tidy else 1
        model.maximize(weight * total + (100 * sum(fruit.values()) - sum(spr.values()) if tidy else 0))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_workers = workers
        # These three searches work on the upper bound. Spare workers improve the plan.
        solver.parameters.subsolvers.extend(['core', 'lb_tree_search', 'objective_lb_search'])
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f'search returned {solver.status_name(status)}')
        hops = {p for p, v in hop.items() if solver.value(v)}
        placed = {p for p, v in spr.items() if solver.value(v)}
        rows = [list(row) for row in board.rows]
        for (x, y), grown in fruit.items():
            if solver.value(grown):
                rows[y][x] = 'A'
        for symbol, tiles in (('T', hops), ('@' if radius == 3 else 'R', placed)):
            for x, y in tiles:
                rows[y][x] = symbol
        rows = [''.join(row) for row in rows]
        self.verify(rows)
        return rows, min(len(soil), int(solver.best_objective_bound) // weight)

    def walk(self, rows, everything=False, seconds=60, workers=8):
        """Shortest closed walk from the door that harvests every trellis crop.

        With `everything`, it also passes over or beside every walkable crop.
        """
        hops, fruit, _, ground = self.verify(rows)
        return shortest_closed_walk(self.board.start, ground, self.pickups(hops, fruit, everything),
                                    seconds, workers)

    def pickups(self, hops, fruit, everything=False):
        pickups = {p: self.stands[p] for p in hops}
        if everything:
            pickups.update((p, self.stands[p] | {p}) for p in fruit)
        return pickups


def plan(name):
    return read_grid(EXAMPLES / (name + '.txt'))


def prove(seconds=600, workers=8):
    for name, (reach, count, sprinkler) in PLANS.items():
        house = Greenhouse(reach=reach)
        hops, fruit, sprinklers, _ = house.verify(plan(name))
        if len(hops) != count or bool(sprinklers) != bool(sprinkler):
            raise ValueError(f'{name} does not match its claim')
        bound = house.solve(RADIUS.get(sprinkler, 0), seconds, workers, tidy=False)[1]
        if bound != count:
            raise RuntimeError(f'{name}: the search stopped with an upper bound of {bound}')
        print(f'{name}: {count} trellis crops is the maximum for {reach} reach '
              f'({"sprinklers" if sprinkler else "Deluxe Retaining Soil"}), '
              f'with {len(fruit)} walkable crops in the lanes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument('--check', type=Path, metavar='PLAN', help='verify a saved plan')
    task.add_argument('--solve', action='store_true', help='search for a maximum plan')
    task.add_argument('--prove', action='store_true', help='confirm every saved maximum')
    parser.add_argument('--reach', choices=sorted(REACH), default='mouse',
                        help='any neighboring tile, side only, or an Iridium Scythe swing')
    parser.add_argument('--sprinklers', choices=sorted(RADIUS),
                        help='with --solve: water with pressure-nozzle (@) or plain (R) iridium sprinklers')
    parser.add_argument('--walk', choices=('daily', 'everything'),
                        help='with --check, find the shortest closed walk')
    parser.add_argument('--replay', type=Path, metavar='WALK', help='with --check, replay a saved walk')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if (args.walk or args.replay) and not args.check:
        parser.error('--walk and --replay need --check')
    if args.prove:
        return prove(max(args.seconds, 600), args.workers)
    house = Greenhouse(reach=args.reach)
    if args.solve:
        rows, bound = house.solve(RADIUS.get(args.sprinklers, 0), args.seconds, args.workers)
        print('\n'.join(rows))
        print(f'{sum(row.count("T") for row in rows)} trellis crops, upper bound {bound}')
        return
    rows = read_grid(args.check)
    hops, fruit, sprinklers, ground = house.verify(rows)
    water = f'{len(sprinklers)} sprinklers' if sprinklers else 'Deluxe Retaining Soil'
    print(f'{len(hops)} trellis crops within {args.reach} reach, {len(fruit)} walkable crops, {water}')
    if args.replay:
        walk = read_walk(house.board.start, args.replay.read_text())
        check_walk(house.board.start, ground, house.pickups(hops, fruit), walk)
        print(f'{len(walk)-1} steps harvest every trellis crop and return to the door')
    if args.walk:
        walk, proven = house.walk(rows, args.walk == 'everything', args.seconds, args.workers)
        print(f'{len(walk)-1} steps ({"shortest" if proven else "best found"}): {tokens(walk)}')


if __name__ == '__main__':
    main()
