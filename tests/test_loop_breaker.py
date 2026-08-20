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


class LoopGuardTests(unittest.TestCase):
    def test_abab_pattern_trips_the_guard(self):
        a = ((1, 1), ((0, 4),))
        b = ((0, 1), ((0, 4),))
        self.assertTrue(runner.loop_guard_tripped([a, b, a, b]))

    def test_progressing_states_do_not_trip(self):
        states = [((1, 1), ()), ((1, 2), ()), ((1, 3), ()), ((1, 4), ())]
        self.assertFalse(runner.loop_guard_tripped(states))

    def test_short_history_never_trips(self):
        a = ((1, 1), ())
        self.assertFalse(runner.loop_guard_tripped([a, a, a]))


class ReenableTests(unittest.TestCase):
    def test_cooldown_elapsed_reenables(self):
        self.assertTrue(runner.should_reenable(10, 50))

    def test_cooldown_still_running_keeps_disabled(self):
        self.assertFalse(runner.should_reenable(10, 49))

    def test_never_disabled_never_reenables(self):
        self.assertFalse(runner.should_reenable(None, 200))


if __name__ == "__main__":
    unittest.main()
