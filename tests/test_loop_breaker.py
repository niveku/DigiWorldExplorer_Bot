import unittest

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner


def empty_grid():
    return {
        (row, col): {
            "player": 0.0,
            "orange": 0.0,
            "pink": 0.0,
            "green": 0.0,
            "item": 0.0,
            "pyramid": 0.0,
            "highlight": 1.0,
        }
        for row in range(5)
        for col in range(5)
    }


class IgnoredTargetsTests(unittest.TestCase):
    def test_ignored_orange_is_not_chased(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, ignored_targets={(0, 4)})
        self.assertEqual(reason, "explore right")

    def test_other_items_stay_attractive(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(0, 4)].update(item=0.10, orange=0.10)
        info[(4, 1)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, ignored_targets={(0, 4)})
        self.assertTrue(reason.startswith("orange"))
        self.assertIn("(4, 1)", reason)
        self.assertNotIn("(0, 4)", reason)

    def test_ignored_cell_is_skipped_as_direct_horizontal_item(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info, ignored_targets={(2, 3)})
        self.assertEqual(reason, "explore right")


class ExploreBanTests(unittest.TestCase):
    def test_banned_cell_is_avoided_during_exploration(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(3, 2)]["pyramid"] = 0.25
        info[(2, 1)]["pyramid"] = 0.25
        action, reason = strategy.choose(info, attacks_enabled=False,
                                         dashes_enabled=False,
                                         ignored_targets={(3, 0)})
        self.assertEqual(reason, "explore right")
        self.assertNotEqual(action[1], (3, 0))

    def test_fully_banned_pocket_still_moves_instead_of_stalling(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(3, 2)]["pyramid"] = 0.25
        info[(2, 1)]["pyramid"] = 0.25
        info[(4, 1)]["pyramid"] = 0.25
        action, reason = strategy.choose(info, attacks_enabled=False,
                                         dashes_enabled=False,
                                         ignored_targets={(3, 0)})
        self.assertIsNotNone(action)
        self.assertEqual(action[1], (3, 0))


class AdjacentItemTests(unittest.TestCase):
    def test_adjacent_pickup_beats_distant_orange(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 1)].update(item=0.10, green=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (3, 1), "down"))
        self.assertTrue(reason.startswith("adjacent item"))

    def test_no_detour_for_non_adjacent_items_when_orange_exists(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 0)].update(item=0.10, green=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("orange"))


class LoopGuardTests(unittest.TestCase):
    def test_abab_pattern_trips_the_guard(self):
        a = ((1, 1), ((0, 4),))
        b = ((0, 1), ((0, 4),))
        self.assertTrue(runner.loop_guard_tripped([a, b, a, b]))

    def test_progressing_states_do_not_trip(self):
        states = [((1, 1), ()), ((1, 2), ()), ((1, 3), ()), ((1, 4), ())]
        self.assertFalse(runner.loop_guard_tripped(states))

    def test_stuck_in_place_trips_after_three_identical_states(self):
        a = ((1, 1), ())
        self.assertFalse(runner.loop_guard_tripped([a, a]))
        self.assertTrue(runner.loop_guard_tripped([a, a, a]))

    def test_period_three_cycle_trips(self):
        a, b, c = ((3, 1), ((0, 1),)), ((2, 1), ()), ((1, 1), ())
        self.assertFalse(runner.loop_guard_tripped([a, b, c, a, b, c]))
        self.assertTrue(runner.loop_guard_tripped([a, b, c, a, b, c, a]))


class ItemMemoryTests(unittest.TestCase):
    def grid(self):
        return {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 0.2}
            for row in range(5) for col in range(5)
        }

    def test_remembered_item_survives_suppression(self):
        info = self.grid()  # item at (0,1) already wiped by suppression
        remembered = {(0, 1): ("orange", 10)}
        merged = runner.merge_remembered_items(info, remembered, player=(1, 1))
        self.assertGreater(merged[(0, 1)]["item"], 0.06)
        self.assertGreater(merged[(0, 1)]["orange"], 0.06)

    def test_player_cell_is_never_reinjected(self):
        info = self.grid()
        remembered = {(1, 1): ("orange", 10)}
        merged = runner.merge_remembered_items(info, remembered, player=(1, 1))
        self.assertEqual(merged[(1, 1)]["item"], 0.0)

    def test_scroll_shifts_remembered_items_left(self):
        remembered = {(0, 1): ("orange", 5), (2, 0): ("green", 7)}
        shifted = runner.shift_items_left(remembered)
        self.assertEqual(shifted, {(0, 0): ("orange", 5)})


class ReenableTests(unittest.TestCase):
    def test_cooldown_elapsed_reenables(self):
        self.assertTrue(runner.should_reenable(10, 50))

    def test_cooldown_still_running_keeps_disabled(self):
        self.assertFalse(runner.should_reenable(10, 49))

    def test_never_disabled_never_reenables(self):
        self.assertFalse(runner.should_reenable(None, 200))


if __name__ == "__main__":
    unittest.main()
