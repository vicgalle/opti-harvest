import unittest

from closed_walk import check_walk
from island_route import read_walk
from machine_room import EXAMPLES, PLANS, WALKS, Room, plan

# Small rooms with the best counts from a brute-force search over every layout:
# (any neighboring tile, side only).
SMALL_ROOMS = {
    (14, 11): ['XXXXXXX', 'X.....X', 'X.....X', 'X.....X', 'X.....X', 'XXXEXXX'],
    (11, 9): ['XXXXXXX', 'X...XXX', 'X...XXX', 'X.....X', 'X.....X', 'XXXXEXX'],
    (9, 7): ['XXXXXXX', 'X.....X', 'X..X..X', 'X.....X', 'XXXXEXX'],
}


class MachineRoomTests(unittest.TestCase):
    def test_saved_plans_hold_their_claimed_machines(self):
        for name, (count, side_only) in PLANS.items():
            room = Room(plan(name), side_only=side_only)
            room.verify()
            self.assertEqual(len(room.machines), count, name)

    def test_counting_bound_settles_both_sheds(self):
        for name, floor in (('shed', 99), ('big-shed', 204)):
            room = Room(plan(name))
            self.assertEqual(len(room.sites), floor)
            self.assertEqual(room.upper_bound(), PLANS[name][0])
        self.assertEqual(Room(plan('cellar')).upper_bound(), 126)

    def test_side_only_rule_is_stricter(self):
        for name in ('shed', 'big-shed', 'cellar'):
            with self.assertRaisesRegex(ValueError, 'no reachable pickup'):
                Room(plan(name), side_only=True).verify()

    def test_sealed_machine_is_rejected(self):
        rows = [row.replace('.', 'M') for row in plan('shed')]
        with self.assertRaisesRegex(ValueError, 'no reachable pickup'):
            Room(rows).verify()

    def test_saved_walks_pass_every_machine(self):
        for name, steps in WALKS.items():
            room = Room(plan(name), side_only=PLANS[name][1])
            ground = room.verify()
            walk = read_walk(room.board.start, (EXAMPLES / (name + '-walk.txt')).read_text())
            check_walk(room.board.start, ground, {p: room.stands[p] for p in room.machines}, walk)
            self.assertEqual(len(walk) - 1, steps, name)

    def test_small_room_search_matches_brute_force(self):
        for counts, rows in SMALL_ROOMS.items():
            for side_only, best in zip((False, True), counts):
                room = Room(rows, side_only=side_only)
                found, bound = room.solve(seconds=30, workers=1)
                plan_found = Room(found, side_only=side_only)
                plan_found.verify()
                self.assertEqual((len(plan_found.machines), bound), (best, best))

if __name__ == '__main__':
    unittest.main()
