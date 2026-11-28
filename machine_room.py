"""Fill a shed or the cellar with machines the farmer can still walk to and collect."""
import argparse
from pathlib import Path

from ortools.sat.python import cp_model

from apiary import AROUND, STEPS, neighbors
from closed_walk import check_walk, shortest_closed_walk, tokens
from island import Island
from island_route import read_walk

EXAMPLES = Path(__file__).parent / 'examples' / 'machine-rooms'
# Saved plan: (machines, side-only pickups)
PLANS = {'shed': (67, False), 'shed-side': (62, True),
         'big-shed': (137, False), 'big-shed-side': (131, True),
         'cellar': (125, False), 'cellar-side': (119, True)}
# Saved round trip: steps
WALKS = {'shed': 64, 'shed-side': 74, 'big-shed': 134, 'big-shed-side': 146,
         'cellar': 132, 'cellar-side': 144}


class Room:
    """A plan uses M for a machine, . for open floor, W for floor that takes no
    machine, E where the farmer arrives and X for walls."""

    def __init__(self, rows, *, side_only=False):
        if not rows or set(''.join(rows)) - set('.MWEX'):
            raise ValueError('use M, ., W, E and X')
        self.board = Island([row.replace('M', '.') for row in rows])
        self.side_only = side_only
        self.sites = self.board.build
        self.machines = {p for p in self.sites if rows[p[1]][p[0]] == 'M'}
        reach = STEPS if side_only else AROUND
        self.stands = {p: self.board.floor.intersection(neighbors(p, reach)) for p in self.sites}

    def verify(self):
        """Independently flood the open floor from the entrance and check every pickup."""
        ground = self.board.flood(self.board.start, self.board.floor - self.machines)
        if self.board.entries - ground:
            raise ValueError('an arrival tile is cut off')
        for p in sorted(self.machines):
            if not self.stands[p] & ground:
                raise ValueError(f'no reachable pickup for the machine at {p}')
        return ground

    def upper_bound(self):
        """Every step onto a new floor tile brings at most three new tiles within reach.

        With F machine sites, A of them within reach of the fixed arrival tiles and
        w open sites, the machines number at most F - w and at most A + 2w.
        """
        fixed = self.board.floor - self.sites
        near = {p for p in self.sites if self.stands[p] & fixed}
        return (len(near) + 2 * len(self.sites)) // 3

    def grid(self, machines):
        rows = [list(row) for row in self.board.rows]
        for x, y in machines:
            rows[y][x] = 'M'
        return [''.join(row) for row in rows]

    def solve(self, seconds=60, workers=8):
        """Return (plan rows, proven upper bound). The saved machines seed the search.

        Each open tile is entered from one neighbor nearer the entrance, and each
        machine keeps an open tile within reach. Stepping onto a tile brings exactly
        three more tiles into reach: the three ahead with diagonal pickups, or the one
        ahead and the two beside it with side-only pickups. Every machine and every
        open tile names a step that first reached it.
        """
        model = cp_model.CpModel()
        fixed = self.board.floor - self.sites
        if self.board.flood(self.board.start, fixed) != fixed:
            raise ValueError('the arrival tiles must be connected')
        machine = {p: model.new_bool_var(f'M{p}') for p in sorted(self.sites)}
        open_ = {p: model.new_bool_var(f'O{p}') for p in sorted(self.sites)}
        depth = {p: model.new_int_var(0, len(self.sites), f'd{p}') for p in sorted(self.sites)}
        reached_by = {p: [] for p in self.sites}
        entered = {}
        for (x, y), walk in open_.items():
            model.add_at_most_one(walk, machine[x, y])
            model.add(depth[x, y] == 0).only_enforce_if(~walk)
            steps = []
            for dx, dy in STEPS:
                parent = (x - dx, y - dy)
                if parent not in self.board.floor:
                    continue
                step = entered[x, y, dx, dy] = model.new_bool_var('step')
                steps.append(step)
                if parent in self.sites:
                    # Depth is the walking distance from the arrival tiles, which leaves
                    # one labeling per layout: open neighbors differ by at most one.
                    model.add_implication(step, open_[parent])
                    model.add(depth[x, y] == depth[parent] + 1).only_enforce_if(step)
                    model.add(depth[x, y] <= depth[parent] + 1).only_enforce_if(walk, open_[parent])
                else:
                    model.add(depth[x, y] == 1).only_enforce_if(walk)
                ahead = (x + dx, y + dy)
                beside = ((x + dy, y + dx), (x - dy, y - dx))
                gained = beside if self.side_only else [(a + dx, b + dy) for a, b in beside]
                for q in (ahead, *gained):
                    if q in reached_by:
                        reached_by[q].append(step)
            model.add(sum(steps) == walk)
        near = {p for p in self.sites if self.stands[p] & fixed}
        for p, placed in machine.items():
            model.add_hint(placed, int(p in self.machines))
            # A best plan leaves no tile empty that an open tile can reach.
            if p in near:
                model.add_bool_or(placed, open_[p])
                continue
            for q in sorted(self.stands[p]):
                model.add_bool_or(~open_[q], placed, open_[p])
            model.add_bool_or([~placed] + [open_[q] for q in sorted(self.stands[p])])
            model.add(placed + open_[p] <= sum(reached_by[p]))
        if self.side_only:
            # A corner wastes reach: the tile inside the turn is reached from both arms.
            for (x, y, dx, dy), first in entered.items():
                for ex, ey in ((dy, dx), (-dy, -dx)):
                    then = entered.get((x + ex, y + ey, ex, ey))
                    inside = (x + ex - dx, y + ey - dy)
                    if then is not None and inside in self.sites - near:
                        model.add(sum(reached_by[inside]) >= machine[inside] + open_[inside] + first + then - 1)
        # Without an open tile beside the arrival tiles, only the `near` sites can hold machines.
        model.add_bool_or(open_[p] for p in sorted(self.sites) if self.board.sides[p] & fixed)
        total = sum(machine.values())
        model.add(total <= len(near) + 2 * sum(open_.values()))
        model.maximize(total)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_workers = workers
        # These three searches work on the upper bound. Spare workers improve the plan.
        solver.parameters.subsolvers.extend(['core', 'lb_tree_search', 'objective_lb_search'])
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f'search returned {solver.status_name(status)}')
        rows = self.grid({p for p, v in machine.items() if solver.value(v)})
        Room(rows, side_only=self.side_only).verify()
        return rows, max(len(near), min(self.upper_bound(), int(solver.best_objective_bound)))

    def walk(self, seconds=60, workers=8):
        ground = self.verify()
        return shortest_closed_walk(self.board.start, ground,
                                    {p: self.stands[p] for p in self.machines}, seconds, workers)


def plan(name):
    return (EXAMPLES / (name + '.txt')).read_text().splitlines()


def prove(seconds=1800, workers=8):
    for name, (count, side_only) in PLANS.items():
        room = Room(plan(name), side_only=side_only)
        room.verify()
        if len(room.machines) != count:
            raise ValueError(f'{name} does not hold the claimed {count} machines')
        bound, how = room.upper_bound(), 'counting bound'
        if bound > count:
            bound, how = room.solve(seconds, workers)[1], 'CP-SAT bound'
        if bound != count:
            raise RuntimeError(f'{name}: the search stopped with an upper bound of {bound}')
        print(f'{name}: {count} machines is the maximum ({how})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument('--check', type=Path, metavar='PLAN', help='verify a saved plan')
    task.add_argument('--solve', type=Path, metavar='PLAN', help='search the same room again')
    task.add_argument('--prove', action='store_true', help='confirm every saved maximum')
    parser.add_argument('--side-only', action='store_true',
                        help='collect only from directly north, south, east or west of a machine')
    parser.add_argument('--walk', action='store_true', help='with --check, find the shortest closed walk')
    parser.add_argument('--replay', type=Path, metavar='WALK', help='with --check, replay a saved walk')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if (args.walk or args.replay) and not args.check:
        parser.error('--walk and --replay need --check')
    if args.prove:
        return prove(max(args.seconds, 1800), args.workers)
    room = Room((args.check or args.solve).read_text().splitlines(), side_only=args.side_only)
    if args.solve:
        rows, bound = room.solve(args.seconds, args.workers)
        count = sum(row.count('M') for row in rows)
        print('\n'.join(rows))
        print(f'{count} machines, upper bound {bound}')
        return
    ground = room.verify()
    print(f'{len(room.machines)} reachable machines on {len(room.sites)} floor tiles, '
          f'counting bound {room.upper_bound()}')
    pickups = {p: room.stands[p] for p in room.machines}
    if args.replay:
        walk = read_walk(room.board.start, args.replay.read_text())
        check_walk(room.board.start, ground, pickups, walk)
        print(f'{len(walk)-1} steps collect every machine and return to the entrance')
    if args.walk:
        walk, proven = room.walk(args.seconds, args.workers)
        print(f'{len(walk)-1} steps ({"shortest" if proven else "best found"}): {tokens(walk)}')


if __name__ == '__main__':
    main()
