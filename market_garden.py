"""Optimize and replay a 28-morning summer farm shop with daily provisions."""

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent / 'examples' / 'summer-market'
DAYS = range(1, 29)
# The outer ring of a 5x5 bed has 16 tiles. Leave one as a walk-in opening.
HOPS_PER_BED = 15
# First harvest when watered on Summer 1, regrowth interval, minimum yield.
CROPS = {'bean': (11, 2, 4), 'pepper': (6, 3, 1), 'hops': (12, 1, 1), 'berry': (14, 4, 3)}
# Loads mature at a morning visit this many days later.
BATCH = {
    'coffee': ('keg', 1, 'bean', 5),
    'ale': ('keg', 2, 'hops', 1),
    'pepper_jelly': ('jar', 3, 'pepper', 1),
    'berry_jelly': ('jar', 3, 'berry', 1),
    'pickled_hops': ('jar', 3, 'hops', 1),
    'pepper_wine': ('keg', 7, 'pepper', 1),
    'berry_wine': ('keg', 7, 'berry', 1),
    'peach_wine': ('keg', 7, 'peach', 1),
    'peach_jelly': ('jar', 3, 'peach', 1),
    'cheese': ('press', 1, 'milk', 1),
}
PRICE = {
    'bean': 15,
    'pepper': 44,
    'hops': 27,
    'berry': 55,
    'milk': 125,
    'coffee': 150,
    'ale': 420,
    'berry_jelly': 210,
    'pepper_jelly': 182,
    'pickled_hops': 140,
    'berry_wine': 210,
    'pepper_wine': 168,
    'cheese': 322,
    'peach': 154,
    'peach_wine': 588,
    'peach_jelly': 462,
}


@dataclass(frozen=True)
class Budget:
    sprinklers: int
    cows: int
    keg: int
    jar: int
    press: int
    crew: int
    peaches: int
    shots: int = 2  # Triple Shot Espressos per person per provision morning.


PRESETS = {'four-corners': Budget(4, 4, 36, 12, 4, 4, 2), 'everfarm': Budget(24, 8, 144, 48, 8, 8, 8)}


def yield_on(crop, day):
    first, interval, qty = CROPS[crop]
    return qty if day >= first and (day - first) % interval == 0 else 0


def solve(b, seconds):
    model = cp_model.CpModel()
    plants = {c: model.new_int_var(0, 24 * b.sprinklers, c) for c in CROPS}
    model.add(sum(plants.values()) <= 24 * b.sprinklers)
    model.add(plants['hops'] <= HOPS_PER_BED * b.sprinklers)
    launches = {p: {} for p in BATCH}
    for p, (machine, duration, _, _) in BATCH.items():
        for day in DAYS:
            launches[p][day] = (
                model.new_int_var(0, getattr(b, machine), f'{p}_{day}') if day + duration <= 28 else 0
            )

    stock = dict.fromkeys(PRICE, 0)
    for day in DAYS:
        for m in ('keg', 'jar', 'press'):
            active = [
                launches[p][d]
                for p, (machine, duration, _, _) in BATCH.items()
                if machine == m
                for d in range(max(1, day - duration + 1), day + 1)
            ]
            model.add(sum(active) <= getattr(b, m))
        for crop, n in plants.items():
            stock[crop] += n * yield_on(crop, day)
        stock['milk'] += b.cows
        stock['peach'] += b.peaches
        for product, (_, duration, raw, qty) in BATCH.items():
            stock[product] += launches[product].get(day - duration, 0)
            stock[raw] -= qty * launches[product][day]
        if day >= 12:
            stock['pepper'] -= b.crew
            stock['cheese'] -= b.crew
            stock['coffee'] -= 3 * b.crew * b.shots
        for item in PRICE:
            model.add(stock[item] >= 0)
        # Without fertilizer, there are three possible bean qualities. Up to
        # four per stack cannot fill a keg. Eight spare beans guarantee the
        # required number of five-bean batches even in the worst split.
        if day >= 11:
            brewing = model.new_bool_var(f'brewing_by_{day}')
            cumulative = sum(launches['coffee'][d] for d in range(11, day + 1))
            model.add(cumulative == 0).only_enforce_if(~brewing)
            model.add(stock['bean'] >= 8).only_enforce_if(brewing)
    gross = sum(stock[item] * price for item, price in PRICE.items())
    model.maximize(gross)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 8
    solver.parameters.max_time_in_seconds = seconds
    status = solver.solve(model)
    if status != cp_model.OPTIMAL:
        label = solver.status_name(status)
        if status == cp_model.FEASIBLE:
            label += f' ({solver.objective_value:g}g, bound {solver.best_objective_bound:g}g)'
        raise ValueError(f'no certified optimum: {label}')
    return {
        'budget': asdict(b),
        'plants': {c: solver.value(v) for c, v in plants.items()},
        'loads': [{p: solver.value(launches[p][d]) for p in BATCH} for d in DAYS],
        'gross': round(solver.objective_value),
        'upper_bound': round(solver.best_objective_bound),
    }


def replay(plan):
    b = Budget(**plan['budget'])
    if any(type(v) is not int or v < 0 for v in asdict(b).values()):
        raise ValueError('invalid budget')
    plants = plan['plants']
    if (
        set(plants) != set(CROPS)
        or any(type(n) is not int or n < 0 for n in plants.values())
        or sum(plants.values()) > 24 * b.sprinklers
        or plants['hops'] > HOPS_PER_BED * b.sprinklers
        or len(plan['loads']) != 28
    ):
        raise ValueError('invalid field or calendar')
    pantry, pending, brewed = Counter(), [], False
    for day, loads in zip(DAYS, plan['loads']):
        if set(loads) != set(BATCH) or any(type(n) is not int or n < 0 for n in loads.values()):
            raise ValueError(f'invalid machine loads on Summer {day}')
        for due, product, n in pending:
            if due == day:
                pantry[product] += n
        pending = [job for job in pending if job[0] > day]
        pantry['milk'] += b.cows
        pantry['peach'] += b.peaches
        for crop, n in plants.items():
            pantry[crop] += n * yield_on(crop, day)
        if day >= 12:
            pantry.subtract({'pepper': b.crew, 'cheese': b.crew, 'coffee': 3 * b.crew * b.shots})
        for product, n in loads.items():
            _, duration, raw, qty = BATCH[product]
            if n:
                pending.append((day + duration, product, n))
                pantry[raw] -= n * qty
        active = Counter()
        for _, product, n in pending:
            active[BATCH[product][0]] += n
        if any(n > getattr(b, machine) for machine, n in active.items()):
            raise ValueError(f'double-booked machine on Summer {day}')
        brewed |= loads['coffee'] > 0
        if min(pantry.values()) < 0 or (brewed and pantry['bean'] < 8):
            raise ValueError(f'ingredient shortfall on Summer {day}')
    gross = sum(pantry[item] * price for item, price in PRICE.items())
    if pending or gross != plan['gross'] or plan.get('upper_bound') != gross:
        raise ValueError('incomplete batches or incorrect sales total')
    return pantry


def calendar(plan, stream):
    """Export the chosen morning loads. One table row is one visit to each machine."""
    b = Budget(**plan['budget'])
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(
        [
            'Summer day',
            'Bean harvest',
            'Pepper harvest',
            'Hops harvest',
            'Blueberry harvest',
            'Milk',
            'Peaches',
            *[f'Load {p.replace("_", " ")}' for p in BATCH],
            'Pack poppers',
            'Pack triple shots',
        ]
    )
    for day, loads in zip(DAYS, plan['loads']):
        writer.writerow(
            [
                day,
                *[yield_on(c, day) * plan['plants'][c] for c in CROPS],
                b.cows,
                b.peaches,
                *[loads[p] for p in BATCH],
                b.crew if day >= 12 else 0,
                b.crew * b.shots if day >= 12 else 0,
            ]
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('farm', choices=PRESETS)
    parser.add_argument('--solve', action='store_true', help='optimize a new calendar')
    parser.add_argument('--crew', type=int, help='daily Pepper Poppers from Summer 12')
    parser.add_argument('--shots', type=int, help='Triple Shot Espressos per person and provision day')
    parser.add_argument('--kegs', type=int)
    parser.add_argument('--jars', type=int)
    parser.add_argument('--sprinklers', type=int)
    parser.add_argument('--cows', type=int)
    parser.add_argument('--peaches', type=int, help='mature peach trees at the start of summer')
    parser.add_argument('--presses', type=int)
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--calendar', action='store_true', help='print the morning checklist as CSV')
    parser.add_argument('--output', type=Path, help='save a newly optimized production plan')
    args = parser.parse_args()
    overrides = {
        k: v
        for k, v in [
            ('crew', args.crew),
            ('shots', args.shots),
            ('keg', args.kegs),
            ('jar', args.jars),
            ('press', args.presses),
            ('sprinklers', args.sprinklers),
            ('cows', args.cows),
            ('peaches', args.peaches),
        ]
        if v is not None
    }
    if args.seconds <= 0 or any(v < 0 for v in overrides.values()):
        parser.error('budgets must be nonnegative and the time limit positive')
    try:
        if args.solve or overrides or args.output:
            plan = solve(replace(PRESETS[args.farm], **overrides), args.seconds)
        else:
            plan = json.loads((HERE / f'{args.farm}.json').read_text())
        pantry = replay(plan)
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
    if args.output:
        args.output.write_text(json.dumps(plan, indent=2) + '\n')
    if args.calendar:
        calendar(plan, sys.stdout)
        return
    b = Budget(**plan['budget'])
    print(
        f'{17*b.crew} Pepper Poppers, {17*b.crew*b.shots} Triple Shot Espressos; {plan["gross"]:,}g in sales'
    )
    print('Plant:', plan['plants'])
    print('Ship:', {item: pantry[item] for item in PRICE if pantry[item]})
    print('CP-SAT upper bound:', plan['upper_bound'])


if __name__ == '__main__':
    main()
