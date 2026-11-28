import unittest
from importlib import import_module

plan = import_module('examples.boardwalk-apiary.plan')


def replay(farm, walks):
    sites = plan.read_sites(plan.HERE / f'{farm}-sites.txt')
    records = plan.read_records(plan.HERE / walks)
    return plan.verify(plan.Terrain(farm), sites, records)


class BoardwalkTests(unittest.TestCase):
    def test_everfarm_houses_area_and_six_yard_returns(self):
        marks, routes, box, active = replay('everfarm', 'everfarm-walks.txt')
        self.assertEqual((sum(c == 'H' for c in marks.values()), box, active), (5180, (181, 143), 8442))
        self.assertEqual({k: len(w)-1 for k, w in routes.items()},
                         dict(A=324, B=826, C=1158, D=1136, E=1126, F=1452))

    def test_beach_rotation_covers_same_stack_as_single_walk(self):
        marks, routes, _, _ = replay('beach', 'beach-walks.txt')
        daily_marks, daily, _, _ = replay('beach', 'beach-daily.txt')
        self.assertEqual(marks, daily_marks)
        self.assertEqual(sum(c == 'H' for c in marks.values()), 999)
        self.assertEqual(len(routes['A'])-1, 842)
        self.assertEqual([len(daily[str(k)])-1 for k in range(1, 5)], [182, 266, 348, 362])

    def test_incomplete_lap_is_rejected_even_if_other_tours_visit_nearby(self):
        terrain = plan.Terrain('beach')
        sites = plan.read_sites(plan.HERE / 'beach-sites.txt')
        records = plan.read_records(plan.HERE / 'beach-daily.txt')
        records[0] = records[0][:-1]
        with self.assertRaisesRegex(ValueError, 'fails to complete'):
            plan.verify(terrain, sites, records)
