import csv
import json
import unittest
from importlib import import_module
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from market_garden import BATCH, HERE, Budget, calendar, replay, solve

layout = import_module('examples.summer-market.layout')


def saved(name):
    return json.loads((HERE / f'{name}.json').read_text())


class MarketGardenTests(unittest.TestCase):
    def test_both_estates_deliver_their_orders_and_replay_every_route(self):
        for name, gross, people, pairs, walks in [
            ('four-corners', 100292, 4, 6, dict(shops=68, full=172, D=72)),
            ('everfarm', 731980, 8, 28, dict(shops=106, full=722, D=146, T=146)),
        ]:
            with self.subTest(name=name):
                plan = saved(name)
                self.assertEqual(plan['gross'], gross)
                self.assertEqual(layout.process(name, plan, HERE, False), (pairs, walks))
                output = StringIO()
                calendar(plan, output)
                self.assertEqual(output.getvalue(), (HERE / f'{name}-calendar.csv').read_text())
                days = list(csv.DictReader(StringIO(output.getvalue())))
                self.assertEqual([int(d['Pack poppers']) for d in days], [0] * 11 + [people] * 17)
                self.assertEqual([int(d['Pack triple shots']) for d in days], [0] * 11 + [people * 2] * 17)

    def test_last_morning_milk_can_ship_but_cannot_become_cheese(self):
        plan = solve(Budget(sprinklers=0, cows=1, keg=0, jar=0, press=1, crew=0, peaches=0), 10)
        self.assertEqual(plan['upper_bound'], 27 * 322 + 125)
        self.assertEqual(replay(plan)['cheese'], 27)
        plan['loads'][-1]['cheese'] = 1
        with self.assertRaisesRegex(ValueError, 'incomplete batches'):
            replay(plan)

    def test_one_bed_and_six_kegs_can_run_the_published_solo_calendar(self):
        plan = solve(Budget(sprinklers=1, cows=1, keg=6, jar=2, press=1, crew=1, peaches=0), 10)
        self.assertEqual(plan['upper_bound'], 9891)
        plan['plants'] = dict(bean=17, pepper=3, hops=0, berry=4)
        with (HERE / 'one-bed-calendar.csv').open() as f:
            plan['loads'] = [
                {p: int(row[f'Load {p.replace("_", " ")}']) for p in BATCH} for row in csv.DictReader(f)
            ]
        with TemporaryDirectory() as directory:
            checked = layout.process('four-corners', plan, Path(directory), True)
            self.assertEqual(checked[0], 3)
            self.assertEqual(checked, layout.process('four-corners', plan, Path(directory), False))

    def test_missed_first_coffee_brew_fails_the_next_morning(self):
        plan = saved('four-corners')
        plan['loads'][10]['coffee'] = 0
        with self.assertRaisesRegex(ValueError, 'ingredient shortfall on Summer 12'):
            replay(plan)

    def test_matching_quality_beans_are_reserved(self):
        plan = saved('four-corners')
        plan['loads'] = [dict.fromkeys(BATCH, 0) for _ in range(28)]
        plan['plants'] = dict(bean=2, pepper=0, hops=0, berry=0)
        plan['budget']['crew'] = 0
        # Eight total beans can be split 4/4, leaving neither stack large enough.
        plan['loads'][10]['coffee'] = 1
        with self.assertRaisesRegex(ValueError, 'ingredient shortfall on Summer 11'):
            replay(plan)

    def test_kegs_cannot_brew_while_wine_is_still_maturing(self):
        plan = saved('four-corners')
        plan['loads'] = [dict.fromkeys(BATCH, 0) for _ in range(28)]
        plan['budget'].update(crew=0, keg=2)
        plan['loads'][9]['peach_wine'] = 1
        plan['loads'][10]['coffee'] = 2
        with self.assertRaisesRegex(ValueError, 'double-booked machine on Summer 11'):
            replay(plan)
