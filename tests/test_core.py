import unittest
from unittest.mock import patch

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner
import digiworld_bot as bot


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


class CoordinateTests(unittest.TestCase):
    def test_cell_center_is_relative(self):
        board = (100, 200, 600, 700)
        self.assertEqual(bot.cell_center(board, 0, 0), (150, 250))
        self.assertEqual(bot.cell_center(board, 4, 4), (550, 650))


class DeviceSelectionTests(unittest.TestCase):
    def test_prefers_bluestacks_tcp_serial(self):
        rows = [("emulator-5554", "device"), ("127.0.0.1:5555", "device")]
        with patch.object(bot, "_device_rows", return_value=rows):
            self.assertEqual(bot.resolve_serial("adb.exe"), "127.0.0.1:5555")

    def test_requires_explicit_choice_for_ambiguous_devices(self):
        rows = [("127.0.0.1:5565", "device"), ("127.0.0.1:5575", "device")]
        with patch.object(bot, "_device_rows", return_value=rows):
            with self.assertRaises(RuntimeError):
                bot.resolve_serial("adb.exe")


class StrategyTests(unittest.TestCase):
    def test_item_art_overrides_pyramid_color(self):
        self.assertFalse(strategy.is_obstacle({"pyramid": 0.60, "item": 0.09}))

    def test_clipped_pyramid_is_blocked(self):
        self.assertTrue(strategy.is_obstacle({"pyramid": 0.90, "item": 0.02}))

    def test_direct_horizontal_item_beats_distant_orange(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)].update(item=0.09, pink=0.09, pyramid=0.59)
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, attacks_enabled=False)
        self.assertEqual(action, ("move", (2, 2), "right"))
        # The pickup is both adjacent and on the direct route; either rule
        # may claim it, and both produce the same move.
        self.assertTrue(reason.startswith(("adjacent item", "direct horizontal item")))

    def test_explorer_prefers_a_free_cell_over_attacking_sideways(self):
        # A garra costs 200 shards vs 40 for a step: with no goal in sight
        # the explorer must not break a non-blocking pyramid below when a
        # free vertical cell exists (long run 20260820T033221, 5 explore
        # attacks). The forward blocker is still worth attacking.
        info = empty_grid()
        info[(2, 4)]["player"] = 0.2   # right edge: no rightward candidate
        info[(3, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertEqual(action[0], "move")
        self.assertEqual(action[2], "up")

    def test_explorer_still_attacks_the_forward_blocker(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(1, 2)]["pyramid"] = 0.9
        info[(3, 2)]["pyramid"] = 0.9
        action, _ = strategy.choose(info, dashes_enabled=False)
        self.assertEqual(action[0], "attack")
        self.assertEqual(action[1], (2, 2))

    def test_blocked_right_route_uses_vertical_detour(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        action, _ = strategy.choose(info, attacks_enabled=False,
                                    dashes_enabled=False)
        self.assertIn(action[2], ("up", "down"))


class ClawBatchingTests(unittest.TestCase):
    """Run 20260820T180814: with a claw as the only visible pickup the
    runner's item_goals stayed empty (claw scores low on the color "item"
    mask), so 3-move batches overshot the turn cell and the bot ping-ponged
    vertically in column 1 around a claw at (2, 2) for 11 straight moves."""

    def claw_board(self):
        info = empty_grid()
        for values in info.values():
            values["claw"] = 0.0
        info[(2, 2)]["claw"] = 0.2
        return info

    def test_claw_counts_as_pickup_goal(self):
        info = self.claw_board()
        self.assertEqual(runner.pickup_goals(info, (0, 1)), {(2, 2)})

    def test_color_items_still_count_as_pickup_goals(self):
        info = self.claw_board()
        info[(1, 4)].update(item=0.09, orange=0.09)
        self.assertEqual(runner.pickup_goals(info, (0, 1)), {(2, 2), (1, 4)})

    def test_player_cell_is_never_a_goal(self):
        info = self.claw_board()
        self.assertEqual(runner.pickup_goals(info, (2, 2)), set())

    def test_followups_stop_at_the_turn_toward_the_claw(self):
        # Player (0,1) heading down for the claw at (2,2): the batch must
        # stop at (2,1) - the turn cell - instead of overshooting to (3,1).
        info = self.claw_board()
        goals = runner.pickup_goals(info, (0, 1))
        moves = runner.safe_followup_moves(
            info, (0, 1), (1, 1), "down", 2, goals)
        self.assertEqual([m[0] for m in moves], [(2, 1)])

    def test_dash_approaches_move_one_cell_per_screenshot(self):
        # Run 20260820T180814 events 33-35: "pair launch at (3,1)" batched
        # past the launch row ((3,1) then (4,1), then back up beyond it).
        # Both dash approaches must advance one verified cell at a time.
        self.assertTrue(runner.is_single_step_approach("approach dash wall via (3, 2)"))
        self.assertTrue(runner.is_single_step_approach("pair launch at (3, 1)"))
        self.assertFalse(runner.is_single_step_approach("explore right"))
        self.assertFalse(runner.is_single_step_approach("claw targets=[(2, 2)]"))

    def test_followups_never_plan_beyond_a_claw(self):
        # Even without goals the batch must not plan past a claw cell,
        # because its pickup animation changes the frame.
        info = self.claw_board()
        moves = runner.safe_followup_moves(
            info, (0, 2), (1, 2), "down", 3, None)
        self.assertEqual([m[0] for m in moves], [(2, 2)])


class BatchTests(unittest.TestCase):
    def test_batch_three_only_without_items(self):
        self.assertEqual(runner.adaptive_batch_limit(2, set()), 3)
        self.assertEqual(runner.adaptive_batch_limit(2, {(1, 4)}), 2)
        self.assertEqual(runner.adaptive_batch_limit(1, set()), 1)

    def test_item_category_uses_strongest_visible_color(self):
        self.assertEqual(runner.item_category({"orange": .09, "pink": .07, "green": .01}), "orange")
        self.assertIsNone(runner.item_category({"orange": .02, "pink": .03, "green": .01}))

    def test_run_summary_contains_time_and_pickup_totals(self):
        text = runner.run_summary(125, {"orange": 3, "pink": 2, "green": 1})
        self.assertIn("Tiempo total 02:05", text)
        self.assertIn("recogidos: 6", text)
        self.assertIn("Energía 3", text)

    def test_run_summary_reports_exact_orange_hud_difference(self):
        text = runner.run_summary(125, {"orange": 3, "pink": 2, "green": 1}, 7180, 7525)
        self.assertIn("Energía 7.180 -> 7.525 (+345)", text)
        self.assertIn("165,6/min", text)
        self.assertIn("9.936,0/h", text)
    def test_compact_progress_includes_percent_and_eta(self):
        text = runner.progress_summary(20, 200, 100)
        self.assertIn("20/200 (10%)", text)
        self.assertIn("01:40", text)
        self.assertIn("15:00", text)

    def test_compact_progress_speaks_spanish(self):
        # The every-2% status line still said "vergangen/verbleibend"
        # after the Spanish pass (user report 2026-08-20).
        text = runner.progress_summary(20, 200, 100)
        self.assertIn("transcurrido", text)
        self.assertIn("quedan", text)
    def test_debug_status_prioritizes_visible_energy(self):
        text = runner.plan_status("move", "right", "explore right", 2)
        self.assertIn("Energía a la vista", text)
        self.assertIn("2 item(s)", text)

    def test_debug_status_describes_exploration_direction(self):
        text = runner.plan_status("move", "right", "explore right", 0)
        self.assertIn("Explorando hacia la derecha", text)

    def test_followup_stops_before_pyramid(self):
        info = empty_grid()
        info[(2, 4)]["pyramid"] = 0.9
        moves = runner.safe_followup_moves(
            info, (2, 1), (2, 2), "right", 2, set()
        )
        self.assertEqual(moves, [((2, 2), (2, 3))])

    def test_followups_stop_when_distance_to_goals_stalls(self):
        # Run 20260821T200525 n=353-359: the route to (0,3) turns right
        # after one step down, but the second down move kept min-distance
        # flat thanks to the OTHER pickup at (3,3), overshot the turn, and
        # the replan bounced back up - a 6-move ping-pong on a static
        # board. A follow-up must get strictly closer to some goal.
        info = empty_grid()
        moves = runner.safe_followup_moves(
            info, (0, 1), (1, 1), "down", 2, {(0, 3), (3, 3)})
        self.assertEqual(moves, [])

    def test_followups_still_ride_straight_at_a_goal(self):
        info = empty_grid()
        moves = runner.safe_followup_moves(
            info, (2, 0), (2, 1), "right", 1, {(2, 4)})
        self.assertEqual([m[0] for m in moves], [(2, 2)])


class WallStabilityTests(unittest.TestCase):
    """Run 20260821T200525: a 3-pyramid wall one row up was never hunted
    while the bot rode rightward, because every scroll shifted the launch
    cell one column left and the stability check compared raw cells - the
    wall looked new every frame. Stability now compares scroll-adjusted
    positions."""

    def test_wall_shifted_by_scroll_is_the_same_wall(self):
        committed = ((1, 3), 10, 5)      # cell, done, scrolls at sighting
        self.assertTrue(runner.wall_is_stable(
            committed, (1, 2), done=11, scrolls_now=6))

    def test_wall_at_an_unexplained_cell_is_new(self):
        committed = ((1, 3), 10, 5)
        self.assertFalse(runner.wall_is_stable(
            committed, (3, 3), done=11, scrolls_now=6))

    def test_stale_commitment_is_not_stable(self):
        committed = ((1, 3), 10, 5)
        self.assertFalse(runner.wall_is_stable(
            committed, (1, 3), done=15, scrolls_now=5))

    def test_committed_wall_dash_accounts_for_scroll(self):
        committed = ((4, 1), 10, 5)
        self.assertTrue(runner.committed_wall_dash(
            committed, (4, 0), 12, scrolls_now=6))
        self.assertFalse(runner.committed_wall_dash(
            committed, (4, 1), 12, scrolls_now=6))


class PhantomObstacleTests(unittest.TestCase):
    """Run 20260821T203611: ten 'cannot move there' toasts in 200 moves -
    the bot kept walking into pyramids its detector had missed, and the
    next frame often replanned the very same rejected step. A rejection
    from the game is ground truth: that cell IS blocked. It becomes a
    phantom obstacle for a few frames so the router walks around it."""

    def test_rejected_cell_becomes_an_obstacle(self):
        info = empty_grid()
        merged = runner.merge_phantom_obstacles(info, {(2, 2): 9}, done=5)
        self.assertTrue(strategy.is_obstacle(merged[(2, 2)]))

    def test_expired_rejection_is_forgotten(self):
        info = empty_grid()
        merged = runner.merge_phantom_obstacles(info, {(2, 2): 5}, done=5)
        self.assertFalse(strategy.is_obstacle(merged[(2, 2)]))

    def test_other_cells_stay_untouched(self):
        info = empty_grid()
        merged = runner.merge_phantom_obstacles(info, {(2, 2): 9}, done=5)
        self.assertFalse(strategy.is_obstacle(merged[(2, 1)]))


class CompactStateLogTests(unittest.TestCase):
    """The event log carried no pyramids, no item categories and no
    memory, so every forensic session had to reconstruct boards from the
    annotated debug PNGs (user question 2026-08-21: 'are the logs
    optimal?' - they were not). Every decision event now records a
    compact board state."""

    def test_state_records_player_items_pyramids_and_memory(self):
        info = empty_grid()
        info[(0, 3)].update(item=0.09, orange=0.09)
        info[(0, 2)]["pyramid"] = 0.9
        state = runner.compact_state(info, (0, 1), {(3, 3): ("steps", 7)})
        self.assertEqual(state["player"], [0, 1])
        self.assertEqual(state["items"], {"0,3": "orange"})
        self.assertEqual(state["pyramids"], [[0, 2]])
        self.assertEqual(state["remembered"], {"3,3": "steps"})


if __name__ == "__main__":
    unittest.main()
