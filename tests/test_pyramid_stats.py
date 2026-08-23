import unittest

import auto_digiworld_batch2 as runner
import analyze_breaks


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


class AttackResultTests(unittest.TestCase):
    def test_surviving_pyramid_is_not_broken(self):
        values = {"pyramid": 0.90, "item": 0.02, "orange": 0.0, "pink": 0.0, "green": 0.0}
        self.assertEqual(runner.attack_result(values),
                         {"broken": False, "revealed": None})

    def test_cleared_cell_with_orange_reveals_orange(self):
        values = {"pyramid": 0.02, "item": 0.09, "orange": 0.09, "pink": 0.0, "green": 0.0}
        self.assertEqual(runner.attack_result(values),
                         {"broken": True, "revealed": "orange"})

    def test_cleared_empty_cell_reveals_nothing(self):
        values = {"pyramid": 0.02, "item": 0.01, "orange": 0.01, "pink": 0.0, "green": 0.0}
        self.assertEqual(runner.attack_result(values),
                         {"broken": True, "revealed": None})


class DashPathReportTests(unittest.TestCase):
    def test_counts_pyramids_and_items_in_dash_range(self):
        info = empty_grid()
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        info[(2, 4)].update(item=0.09, orange=0.09)
        report = runner.dash_path_report(info, (2, 1))
        self.assertEqual(report["pyramids"], 2)
        self.assertEqual(report["visible_items"], 1)
        self.assertEqual(report["cells_seen"], [[2, 2], [2, 3], [2, 4]])

    def test_path_is_clipped_at_board_edge(self):
        info = empty_grid()
        info[(0, 4)]["pyramid"] = 0.9
        report = runner.dash_path_report(info, (0, 3))
        self.assertEqual(report["pyramids"], 1)
        self.assertEqual(report["cells_seen"], [[0, 4]])


class JitterTests(unittest.TestCase):
    # jittered_delay retired with the CLI interval (2026-08-22, user
    # directive): pacing is internal per action type - see
    # ActionDelayTests in test_dash_wall.
    def test_action_delay_floor_is_deterministic(self):
        self.assertAlmostEqual(
            runner.action_delay("move", rand=lambda: 0.0),
            runner.ACTION_DELAYS["move"])


class EnergyConsensusTests(unittest.TestCase):
    def test_two_equal_reads_confirm_the_value(self):
        self.assertEqual(runner.confirmed_energy(3805, 3805), 3805)

    def test_disagreeing_reads_are_rejected(self):
        self.assertIsNone(runner.confirmed_energy(3555, 3805))

    def test_first_read_alone_is_not_enough(self):
        self.assertIsNone(runner.confirmed_energy(None, 3805))

    def test_unreadable_second_frame_is_rejected(self):
        self.assertIsNone(runner.confirmed_energy(3805, None))

    def test_small_increase_between_frames_is_accepted(self):
        self.assertEqual(runner.confirmed_energy(3805, 3815), 3815)

    def test_digit_confusion_sized_jump_is_rejected(self):
        self.assertIsNone(runner.confirmed_energy(3555, 3805))
        self.assertIsNone(runner.confirmed_energy(3805, 3555))


class FinalEnergyTests(unittest.TestCase):
    """The closing HUD read races the pickup animation.

    Run 20260823T142253 n=39 collected an orange on the last step; the
    flying icon still covered the counter when the final screenshot was
    taken, read_energy_counter returned None, and the whole run reported
    "Contador de energia ilegible" even though 36 of 38 frames had read
    it cleanly. The closing read retries while the animation clears, and
    falls back to the last reading the loop already trusted rather than
    throwing the run's headline number away.
    """

    def test_a_clean_first_read_is_taken_as_is(self):
        reads = iter([40265])
        value, source = runner.final_energy(lambda: next(reads), 3410,
                                            pause=lambda _s: None)
        self.assertEqual((value, source), (40265, "final"))

    def test_an_occluded_read_retries_until_the_animation_clears(self):
        reads = iter([None, None, 40265])
        value, source = runner.final_energy(lambda: next(reads), 3410,
                                            pause=lambda _s: None)
        self.assertEqual((value, source), (40265, "final"))

    def test_a_read_that_never_clears_falls_back_to_the_loop(self):
        value, source = runner.final_energy(lambda: None, 40265,
                                            pause=lambda _s: None)
        self.assertEqual((value, source), (40265, "loop"))

    def test_nothing_readable_anywhere_stays_unknown(self):
        value, source = runner.final_energy(lambda: None, None,
                                            pause=lambda _s: None)
        self.assertEqual((value, source), (None, None))

    def test_retries_are_bounded(self):
        calls = []
        runner.final_energy(lambda: calls.append(1), None,
                            pause=lambda _s: None)
        self.assertLessEqual(len(calls), 4)


class EfficiencyReportTests(unittest.TestCase):
    """What the run cost, in the two currencies that matter.

    The per-frame ledger already proves which taps the game charged for,
    but nothing added them up: a run could waste one tap in ten and the
    closing line would look identical. These are the numbers that say
    whether a pathfinding change paid for itself.
    """

    def test_counts_the_taps_the_game_refused(self):
        report = runner.efficiency_report(claimed=59, charged=53, waits=4,
                                          frames=53, elapsed=71.3,
                                          energy_delta=770)
        self.assertEqual(report["refused"], 6)
        self.assertAlmostEqual(report["refused_share"], 6 / 59)

    def test_energy_per_paw_is_the_run_s_exchange_rate(self):
        report = runner.efficiency_report(claimed=10, charged=10, waits=0,
                                          frames=10, elapsed=10.0,
                                          energy_delta=500)
        self.assertAlmostEqual(report["energy_per_paw"], 50.0)

    def test_an_unknown_energy_delta_stays_unknown(self):
        report = runner.efficiency_report(claimed=10, charged=10, waits=0,
                                          frames=10, elapsed=10.0,
                                          energy_delta=None)
        self.assertIsNone(report["energy_per_paw"])

    def test_a_run_that_never_acted_does_not_divide_by_zero(self):
        report = runner.efficiency_report(claimed=0, charged=0, waits=2,
                                          frames=2, elapsed=3.0,
                                          energy_delta=0)
        self.assertIsNone(report["refused_share"])
        self.assertIsNone(report["energy_per_paw"])

    def test_wait_frames_are_reported_as_a_share_of_all_frames(self):
        report = runner.efficiency_report(claimed=8, charged=8, waits=2,
                                          frames=10, elapsed=10.0,
                                          energy_delta=0)
        self.assertAlmostEqual(report["wait_share"], 0.2)

    def test_the_line_names_both_kinds_of_waste(self):
        line = runner.format_efficiency(
            runner.efficiency_report(claimed=59, charged=53, waits=4,
                                     frames=53, elapsed=71.3,
                                     energy_delta=770))
        self.assertIn("6", line)
        self.assertIn("4", line)


class IdleGuardTests(unittest.TestCase):
    """A run that cannot act must end, not spin.

    Run 20260823T145105 asked for 80 actions, executed 46, and then sat
    in the same refused-garra frame 579 times: --steps was never
    reached, so the loop had no exit. Every skip path is a "replan and
    try again" and each one is individually reasonable; what was missing
    was a ceiling on how many frames in a row may produce no tap at all.
    """

    def test_a_productive_frame_resets_the_count(self):
        self.assertEqual(runner.idle_streak(9, acted=True), 0)

    def test_an_empty_frame_advances_the_count(self):
        self.assertEqual(runner.idle_streak(9, acted=False), 10)

    def test_the_ceiling_is_reached_only_at_the_limit(self):
        limit = runner.MAX_IDLE_FRAMES
        self.assertFalse(runner.idle_exhausted(limit - 1))
        self.assertTrue(runner.idle_exhausted(limit))

    def test_the_ceiling_leaves_room_for_ordinary_waits(self):
        # The board-in-motion and unreliable-board holds cap at 3 and 5;
        # the guard must not fire on a legitimate one.
        self.assertGreater(runner.MAX_IDLE_FRAMES, 15)


class BlockedDirectionTests(unittest.TestCase):
    """How long "do not walk back" stays true.

    The fact it encodes is about the BOARD, not about the frame: while
    nothing scrolled and nothing was collected, the cell we just left is
    still the cell we just left. Run 20260823T150408 n=70-72 lost two
    paws because a wall-stabilizing WAIT sat between the step and the
    replan, the veto was recomputed from an empty receipt, and the
    planner walked straight back to (3, 1).
    """

    def test_a_clean_charged_step_blocks_its_own_reverse(self):
        self.assertEqual(
            runner.next_blocked_direction(None, had_taps=True, claimed=1,
                                          charged=1, belt_shift=0,
                                          picked=False, direction="down"),
            "up")

    def test_a_wait_frame_keeps_the_standing_veto(self):
        self.assertEqual(
            runner.next_blocked_direction("up", had_taps=False, claimed=0,
                                          charged=0, belt_shift=0,
                                          picked=False, direction=None),
            "up")

    def test_a_scroll_clears_it_because_the_board_moved(self):
        self.assertIsNone(
            runner.next_blocked_direction("up", had_taps=True, claimed=1,
                                          charged=1, belt_shift=1,
                                          picked=False, direction="right"))

    def test_a_pickup_clears_it_because_the_step_paid(self):
        self.assertIsNone(
            runner.next_blocked_direction("up", had_taps=True, claimed=1,
                                          charged=1, belt_shift=0,
                                          picked=True, direction="down"))

    def test_a_refused_tap_blocks_nothing(self):
        # Nobody moved, so there is no cell to avoid going back to.
        self.assertIsNone(
            runner.next_blocked_direction("up", had_taps=True, claimed=2,
                                          charged=1, belt_shift=0,
                                          picked=False, direction="down"))

    def test_an_attack_frame_clears_it(self):
        # An attack has no direction and changes the board.
        self.assertIsNone(
            runner.next_blocked_direction("up", had_taps=True, claimed=0,
                                          charged=0, belt_shift=0,
                                          picked=False, direction="up"))


class PurchaseRecommendationTests(unittest.TestCase):
    """Measured net burn across 13 runs / 2,750 actions: 0.78 steps,
    0.033 garras, 0.027 dashes per action (refunds and pickups already
    netted out). The recommendation covers a planned run with a 15%
    margin; steps sell in packs of 50 (2,000 shards), garras at 200,
    dashes at 400."""

    def test_empty_inventory_recommends_full_load(self):
        rec = runner.purchase_recommendation(
            100, {"steps": 0, "attacks": 0, "dashes": 0})
        self.assertEqual(rec["steps"]["deficit"], 90)
        self.assertEqual(rec["steps"]["packs"], 2)
        self.assertEqual(rec["attacks"]["deficit"], 4)
        self.assertEqual(rec["dashes"]["deficit"], 4)
        self.assertEqual(rec["total_shards"], 2 * 2000 + 4 * 200 + 4 * 400)

    def test_full_inventory_needs_nothing(self):
        rec = runner.purchase_recommendation(
            100, {"steps": 500, "attacks": 40, "dashes": 20})
        self.assertEqual(rec["total_shards"], 0)

    def test_partial_inventory_buys_only_the_gap(self):
        rec = runner.purchase_recommendation(
            100, {"steps": 60, "attacks": 4, "dashes": 1})
        self.assertEqual(rec["steps"]["deficit"], 30)
        self.assertEqual(rec["steps"]["packs"], 1)
        self.assertEqual(rec["attacks"]["deficit"], 0)
        self.assertEqual(rec["dashes"]["deficit"], 3)
        self.assertEqual(rec["total_shards"], 2000 + 3 * 400)

    def test_unreadable_counters_are_skipped(self):
        rec = runner.purchase_recommendation(
            100, {"steps": None, "attacks": 5, "dashes": None})
        self.assertNotIn("steps", rec)
        self.assertNotIn("dashes", rec)
        self.assertIn("attacks", rec)


class AffordableActionsTests(unittest.TestCase):
    """The inverse question the launcher asks before a run: with what I
    am carrying, how far can I go, and what runs out first?

    Re-measured 2026-08-23 over 39 recorded runs / 9,650 actions: 0.760
    steps, 0.027 garras, 0.026 dashes per action on the weighted mean,
    and 0.860 / 0.080 / 0.050 in the worst single run - which is why the
    launcher reports a range instead of one confident number.
    """

    def test_it_names_how_far_the_inventory_goes(self):
        reach = runner.affordable_actions({"steps": 780, "attacks": 100,
                                           "dashes": 100})
        # 780 paws at the measured 0.78 per action.
        self.assertEqual(reach["actions"], 1000)
        self.assertEqual(reach["limiting"], "steps")

    def test_the_scarcest_resource_is_the_one_that_binds(self):
        reach = runner.affordable_actions({"steps": 5000, "attacks": 40,
                                           "dashes": 2})
        self.assertEqual(reach["limiting"], "dashes")
        self.assertEqual(reach["actions"], 74)

    def test_an_empty_counter_stops_the_run_at_zero(self):
        reach = runner.affordable_actions({"steps": 0, "attacks": 40,
                                           "dashes": 40})
        self.assertEqual((reach["actions"], reach["limiting"]), (0, "steps"))

    def test_unreadable_counters_are_skipped_not_guessed(self):
        reach = runner.affordable_actions({"steps": None, "attacks": 40,
                                           "dashes": 40})
        self.assertNotIn("steps", reach["per_resource"])
        self.assertEqual(reach["limiting"], "attacks")

    def test_a_fully_unreadable_hud_answers_nothing(self):
        reach = runner.affordable_actions({"steps": None, "attacks": None,
                                           "dashes": None})
        self.assertIsNone(reach["actions"])
        self.assertIsNone(reach["limiting"])

    def test_the_worst_measured_run_gives_the_pessimistic_end(self):
        # A run that leans hard on garras burns three times the average,
        # so the reach is a range and the floor is never above the
        # expectation.
        reach = runner.affordable_actions({"steps": 780, "attacks": 100,
                                           "dashes": 100})
        self.assertEqual(reach["safe_actions"], 906)   # 780 / 0.86
        self.assertLessEqual(reach["safe_actions"], reach["actions"])


class RunPlanTests(unittest.TestCase):
    """What the launcher shows after you type N, before anything is
    tapped: what N costs, what you carry, and how far you could go."""

    def test_it_states_the_need_and_the_stock_of_every_resource(self):
        text = runner.format_run_plan(
            300, {"steps": 3478, "attacks": 30, "dashes": 11})
        for word in ("300", "pasos", "garras", "dashes", "3.478"):
            self.assertIn(word, text)

    def test_a_sufficient_inventory_says_so_plainly(self):
        text = runner.format_run_plan(
            100, {"steps": 5000, "attacks": 40, "dashes": 40})
        self.assertIn("no hay que comprar nada", text)

    def test_a_deficit_names_the_shards(self):
        text = runner.format_run_plan(
            500, {"steps": 10, "attacks": 0, "dashes": 0})
        self.assertIn("shards", text)
        self.assertIn("Compra recomendada", text)

    def test_it_names_what_runs_out_first(self):
        text = runner.format_run_plan(
            100, {"steps": 5000, "attacks": 40, "dashes": 2})
        self.assertIn("dashes", text)
        self.assertIn("74", text)          # 2 / 0.027

    def test_an_unreadable_hud_says_so_instead_of_inventing(self):
        text = runner.format_run_plan(
            100, {"steps": None, "attacks": None, "dashes": None})
        self.assertIn("no se pudo leer", text.lower())


class RevealedTypeTests(unittest.TestCase):
    def test_new_pickup_types_do_not_crash_the_aggregate(self):
        # Pyramids also drop paws/orbs now that pickup types are told
        # apart; the revealed counter must accept any type name.
        events = [{"pyramid_result": {"broken": True, "revealed": "steps"},
                   "action": [{"type": "attack", "target_cell": [2, 2]}]}]
        stats = analyze_breaks.aggregate(events)
        self.assertEqual(stats["revealed"]["steps"], 1)


class WilsonIntervalTests(unittest.TestCase):
    def test_matches_known_value_for_eight_of_ten(self):
        low, high = analyze_breaks.wilson_interval(8, 10)
        self.assertAlmostEqual(low, 0.490, places=2)
        self.assertAlmostEqual(high, 0.943, places=2)

    def test_zero_samples_span_full_range(self):
        self.assertEqual(analyze_breaks.wilson_interval(0, 0), (0.0, 1.0))


class AggregateTests(unittest.TestCase):
    def test_collects_breaks_dashes_and_shard_costs(self):
        events = [
            {"action": [{"type": "move", "target_cell": [2, 2]},
                        {"type": "move", "target_cell": [2, 3]}]},
            {"action": [{"type": "attack", "target_cell": [2, 4]}],
             "pyramid_result": None},
            {"pyramid_result": {"broken": True, "revealed": "orange",
                                "attacks_before": 74, "attacks_after": 74,
                                "counters_before": {"steps": 29, "attacks": 74,
                                                    "green_tickets": 28954,
                                                    "purple_tickets": 28956},
                                "counters_after": {"steps": 29, "attacks": 74,
                                                   "green_tickets": 28955,
                                                   "purple_tickets": 28956}},
             "action": [{"type": "move", "target_cell": [2, 4]}]},
            {"pyramid_result": {"broken": True, "revealed": None},
             "action": "WAIT: overlay visible"},
            {"pyramid_result": {"broken": False, "revealed": None},
             "action": "STOP: no safe action"},
            {"action": [{"type": "dash"}],
             "dash_path": {"pyramids": 2, "visible_items": 1, "cells_seen": []}},
            {"dash_result": {"pyramids_in_path": 2, "visible_items_in_path": 1,
                             "energy_before": 100, "energy_after": 108,
                             "energy_delta": 8,
                             "inventory_before": {"steps": 29, "attacks": 70, "dashes": 33,
                                                  "green_tickets": 28954, "purple_tickets": None},
                             "inventory_after": {"steps": 29, "attacks": 72, "dashes": 32,
                                                 "green_tickets": 28957, "purple_tickets": 28956}}},
            {"dash_result": {"pyramids_in_path": 1, "visible_items_in_path": 0,
                             "energy_before": None, "energy_after": 120,
                             "energy_delta": None}},
        ]
        stats = analyze_breaks.aggregate(events)
        self.assertEqual(stats["attacks_evaluated"], 3)
        self.assertEqual(stats["broken"], 2)
        self.assertEqual(stats["revealed"], {"orange": 1, "pink": 0, "green": 0, "none": 1})
        self.assertEqual(stats["dashes"], 2)
        self.assertEqual(stats["dash_pyramids"], 3)
        self.assertEqual(stats["dash_energy_deltas"], [8])
        self.assertEqual(stats["actions"], {"move": 3, "attack": 1, "dash": 1})
        self.assertEqual(stats["shards_estimate"], 3*40 + 1*200 + 1*400)
        self.assertEqual(stats["attack_inventory_deltas"], [0])
        self.assertEqual(stats["dash_attack_deltas"], [2])
        self.assertEqual(stats["dash_dash_deltas"], [-1])
        self.assertEqual(stats["attacks_real"], 0)
        self.assertEqual(stats["attacks_fake"], 1)
        self.assertEqual(stats["attacks_unverified"], 2)
        self.assertEqual(stats["attack_counter_deltas"]["green_tickets"], [1])
        self.assertEqual(stats["attack_counter_deltas"]["purple_tickets"], [0])
        self.assertEqual(stats["attack_counter_deltas"]["steps"], [0])
        self.assertEqual(stats["dash_counter_deltas"]["green_tickets"], [3])
        self.assertEqual(stats["dash_counter_deltas"]["purple_tickets"], [])
        self.assertEqual(stats["dash_counter_deltas"]["steps"], [0])


if __name__ == "__main__":
    unittest.main()
