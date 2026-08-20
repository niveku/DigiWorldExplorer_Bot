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


def wall(info, row, cols):
    for col in cols:
        info[(row, col)]["pyramid"] = 0.9


class NearestDashWallTests(unittest.TestCase):
    def test_finds_launch_cell_left_of_three_run(self):
        info = empty_grid()
        wall(info, 1, (2, 3, 4))
        self.assertEqual(strategy.nearest_dash_wall(info, (3, 0)), (1, 1))

    def test_wall_touching_left_edge_has_no_launch_cell(self):
        info = empty_grid()
        wall(info, 1, (0, 1, 2))
        self.assertIsNone(strategy.nearest_dash_wall(info, (3, 0)))

    def test_two_run_is_not_a_wall(self):
        info = empty_grid()
        wall(info, 1, (2, 3))
        self.assertIsNone(strategy.nearest_dash_wall(info, (3, 0)))

    def test_prefers_the_nearest_of_two_walls(self):
        info = empty_grid()
        wall(info, 0, (2, 3, 4))
        wall(info, 4, (2, 3, 4))
        self.assertEqual(strategy.nearest_dash_wall(info, (0, 0)), (0, 1))


class IrresistibleDashTests(unittest.TestCase):
    def test_wall_of_three_outranks_orange_items(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "move")
        self.assertTrue(reason.startswith("approach dash wall"))

    def test_dashes_immediately_from_the_launch_cell(self):
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (0, 1), "right"))
        self.assertIn("wall", reason)

    def test_without_dashes_the_wall_is_ignored(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertTrue(reason.startswith("orange"))

    def test_two_pyramids_in_another_row_cause_no_detour(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3))
        action, reason = strategy.choose(info)
        self.assertEqual(reason, "explore right")


class WallHuntGateTests(unittest.TestCase):
    def test_hunting_disabled_ignores_the_wall(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info, hunt_walls=False)
        self.assertEqual(reason, "explore right")

    def test_hunting_enabled_is_the_default(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("approach dash wall"))


class CorridorDashTests(unittest.TestCase):
    def test_second_attack_on_same_row_with_incoming_becomes_dash(self):
        preview = [False, False, False, True, False]
        action = ("attack", (3, 2), "right")
        self.assertTrue(runner.corridor_dash_due(action, (3, 84), 86, preview, True))

    def test_no_preview_keeps_the_attack(self):
        action = ("attack", (3, 2), "right")
        self.assertFalse(runner.corridor_dash_due(action, (3, 84), 86, None, True))
        self.assertFalse(runner.corridor_dash_due(
            action, (3, 84), 86, [False] * 5, True))

    def test_stale_or_other_row_attacks_do_not_count(self):
        preview = [False, False, False, True, False]
        action = ("attack", (3, 2), "right")
        self.assertFalse(runner.corridor_dash_due(action, (3, 80), 86, preview, True))
        self.assertFalse(runner.corridor_dash_due(action, (2, 85), 86, preview, True))
        self.assertFalse(runner.corridor_dash_due(action, None, 86, preview, True))
        self.assertFalse(runner.corridor_dash_due(action, (3, 84), 86, preview, False))


class PairDashTests(unittest.TestCase):
    """Two pyramids inside the 3-cell dash path cost the same 400 shards as
    two garras, but the dash also advances three cells and collects every
    pickup in its path - so it wins whenever no off-path pickup would be
    lost to the forward scroll (runs 20260820T030138/030401 spent 11 garras
    and 0 of 25 dashes on exactly these shapes)."""

    def test_two_adjacent_pyramids_ahead_trigger_a_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (2, 1), "right"))
        self.assertIn("pair", reason)

    def test_gap_pattern_with_orange_in_the_middle_dashes_through(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        wall(info, 3, (2, 4))
        info[(3, 3)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (3, 1), "right"))
        self.assertIn("pair", reason)

    def test_off_path_pickup_the_scroll_would_delete_blocks_the_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(4, 1)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "dash")

    def test_off_path_pickup_far_right_does_not_block(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(4, 4)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (2, 1), "right"))

    def test_single_pyramid_in_path_is_not_enough(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2,))
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "dash")

    def test_preview_supplies_the_second_pyramid_at_the_edge(self):
        info = empty_grid()
        info[(2, 2)]["player"] = 0.2
        wall(info, 2, (4,))
        preview = [False, False, True, False, False]
        action, reason = strategy.choose(info, preview=preview)
        self.assertEqual(action, ("dash", (2, 2), "right"))

    def test_without_dashes_the_pair_is_ignored(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertNotEqual(action[0], "dash")


class PairDashDefersToWallTests(unittest.TestCase):
    """A same-row pair must not preempt a visible wall of three: the wall
    needs two stable frames before hunting engages, and the instant pair
    dash was firing first (long run 20260820T033221: dash on 2 while a
    3-wall sat one row away)."""

    def test_pair_waits_when_a_full_wall_is_visible_elsewhere(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info, hunt_walls=False)
        self.assertNotIn("pair", reason)

    def test_own_row_wall_grade_pair_still_fires(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3, 4))
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info, hunt_walls=False)
        self.assertEqual(action, ("dash", (2, 1), "right"))

    def test_stable_wall_still_outranks_the_pair(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("approach dash wall"))


class PairLaunchApproachTests(unittest.TestCase):
    """One vertical step to a pair launch: the user watched the bot skip
    dashes it could reach by moving a single cell up or down."""

    def test_moves_one_row_down_to_a_pair_launch(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 3, (2, 3))
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (3, 1), "down"))
        self.assertIn("pair launch", reason)

    def test_blocked_launch_cell_is_not_approached(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 3, (1, 2, 3))  # (3,1) itself is a pyramid, not a launch
        action, reason = strategy.choose(info)
        self.assertNotIn("pair launch", reason)

    def test_at_risk_pickup_blocks_the_approach_too(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 3, (2, 3))
        info[(0, 1)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        self.assertNotIn("pair launch", reason)


class LeftmostOrangeTests(unittest.TestCase):
    """The scroll erodes the left side: with several oranges on board the
    leftmost dies first, so it is collected first (the long run leaked
    left-edge oranges while collecting to the right)."""

    def test_left_band_orange_is_collected_before_a_nearer_right_one(self):
        info = empty_grid()
        info[(0, 2)]["player"] = 0.2
        info[(0, 4)].update(item=0.10, orange=0.10)
        info[(3, 2)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action[2], "down")

    def test_all_oranges_on_the_right_keep_nearest_first(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.10, orange=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action[2], "right")


class ClawPickupTests(unittest.TestCase):
    """A claw pickup refunds a 200-shard garra: worth collecting below
    energy priority but above ticket pickups (user-confirmed sightings the
    bot skipped; classifier gave them item=0.023, invisible at 0.06)."""

    def test_lone_claw_is_routed_to(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)]["claw"] = 0.15
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (2, 2), "right"))
        self.assertIn("claw", reason)

    def test_orange_still_outranks_the_claw(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)]["claw"] = 0.15
        info[(4, 3)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("orange"))

    def test_claw_outranks_a_ticket_pickup(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)]["claw"] = 0.15
        info[(1, 3)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("claw", reason)

    def test_adjacent_claw_is_grabbed_first(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 1)]["claw"] = 0.15
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (3, 1), "down"))


class OutOfStepsTests(unittest.TestCase):
    """Run 20260820T030401 burned five rejected taps and a generic exit 6
    after the stamina counter hit 0; a confirmed empty counter plus bouncing
    moves must stop the run with a clear message instead."""

    def test_two_rejections_with_zero_steps_stop_the_run(self):
        self.assertTrue(runner.out_of_steps(
            {"steps": 0, "attacks": 49, "dashes": 26}, rejected_streak=2))

    def test_steps_remaining_keep_running(self):
        self.assertFalse(runner.out_of_steps(
            {"steps": 12, "attacks": 49, "dashes": 26}, rejected_streak=3))

    def test_unreadable_counter_is_not_treated_as_zero(self):
        self.assertFalse(runner.out_of_steps(
            {"steps": None, "attacks": 49, "dashes": 26}, rejected_streak=4))
        self.assertFalse(runner.out_of_steps(None, rejected_streak=4))

    def test_first_rejection_alone_is_not_enough(self):
        self.assertFalse(runner.out_of_steps(
            {"steps": 0, "attacks": 49, "dashes": 26}, rejected_streak=1))


class PerishableOrangeTests(unittest.TestCase):
    def test_left_edge_orange_outranks_a_nearer_right_one(self):
        info = empty_grid()
        info[(2, 2)]["player"] = 0.2
        info[(2, 0)].update(item=0.10, orange=0.10)   # about to scroll away
        info[(2, 4)].update(item=0.10, orange=0.10)   # will keep for a while
        action, reason = strategy.choose(info)
        self.assertEqual(action[1], (2, 1))
        self.assertIn("(2, 0)", reason)

    def test_without_perishables_nearest_orange_wins(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.10, orange=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action[2], "right")


class WallStatusTests(unittest.TestCase):
    def test_wall_approach_gets_its_own_status_line(self):
        text = runner.plan_status("move", "up", "approach dash wall via (0, 1)", 0)
        self.assertIn("Pyramidenwand", text)


if __name__ == "__main__":
    unittest.main()
