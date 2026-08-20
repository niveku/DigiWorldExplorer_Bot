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


class PerishableBeatsWallTests(unittest.TestCase):
    """Run 20260820T061407 events 126/247: the wall dash fired with an
    orange sitting in the left band and the 3-cell advance scrolled it
    off forever. Scroll only advances on rightward moves, so a left
    detour costs the wall nothing - rescue the orange first, dash after."""

    def test_left_band_orange_outranks_the_wall_dash(self):
        info = empty_grid()
        info[(2, 2)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        info[(2, 0)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("orange perishable"))

    def test_wall_still_wins_over_right_side_oranges(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("approach dash wall"))


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


class PickupPriorityTests(unittest.TestCase):
    """Measured values per pickup: dash orb +1 dash (400 shards), paws +5
    steps (200), claw +1 garra (200), tickets +1 (negligible). Mid-tier
    pickups sit between energy and tickets; tickets never veto a dash."""

    def test_dash_orb_outranks_a_nearer_ticket(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 2)].update(item=0.10, green=0.10)             # orb, distance 3
        info[(0, 1)].update(item=0.10, green=0.10, card_green=0.09)  # ticket, distance 2
        action, reason = strategy.choose(info)
        self.assertIn("(4, 2)", reason)
        self.assertNotEqual(action[2], "up")

    def test_paws_outrank_a_nearer_ticket(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 2)].update(item=0.10, pink=0.10)              # paws, distance 3
        info[(0, 1)].update(item=0.10, pink=0.10, white=0.09)  # purple ticket, distance 2
        action, reason = strategy.choose(info)
        self.assertIn("(4, 2)", reason)
        self.assertNotEqual(action[2], "up")

    def test_orange_still_outranks_the_orb(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, green=0.10)
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith(("orange", "direct")))

    def test_a_ticket_does_not_veto_the_pair_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(4, 1)].update(item=0.10, green=0.10, card_green=0.09)  # ticket at risk
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (2, 1), "right"))

    def test_a_left_band_orb_still_vetoes_the_pair_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(4, 1)].update(item=0.10, green=0.10)  # dash orb at risk
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "dash")


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


class ItemsFlickeringTests(unittest.TestCase):
    """194 of 214 WAITs across four runs were the burst guard re-firing on
    plain scroll shifts: the item set 'changed' because every cell moved
    one column left. Only an unexplained disappearance - an item gone
    without scrolling off or being newly collected - suggests a real
    pickup animation."""

    def test_identical_sets_are_stable(self):
        cells = frozenset({(1, 2), (3, 4)})
        self.assertFalse(runner.items_flickering(cells, cells))

    def test_pure_scroll_shift_is_stable(self):
        previous = frozenset({(1, 2), (3, 4)})
        current = frozenset({(1, 1), (3, 3)})
        self.assertFalse(runner.items_flickering(current, previous))

    def test_scroll_with_new_arrivals_is_stable(self):
        previous = frozenset({(1, 2)})
        current = frozenset({(1, 1), (0, 4), (2, 4)})
        self.assertFalse(runner.items_flickering(current, previous))

    def test_scroll_off_the_left_edge_is_stable(self):
        previous = frozenset({(1, 0), (3, 4)})
        current = frozenset({(3, 3)})
        self.assertFalse(runner.items_flickering(current, previous))

    def test_unexplained_disappearance_flickers(self):
        previous = frozenset({(1, 2), (3, 3)})
        current = frozenset({(1, 2)})
        self.assertTrue(runner.items_flickering(current, previous))

    def test_first_frame_has_no_evidence(self):
        self.assertFalse(runner.items_flickering(frozenset({(1, 2)}), None))


class CloseRewardOverlayTests(unittest.TestCase):
    """Run 20260820T052000: the blind 0.6s close tap fired before the
    Reward overlay accepted input; the overlay stayed open and the run
    died on unreliable-board waits. Closing must be verified per tap."""

    class _Det:
        def __init__(self, state, board=(74, 425, 626, 871)):
            self.state = state
            self.board = board if state == "digiworld" else None

    def test_stops_tapping_once_the_board_is_back(self):
        taps = []
        states = iter(["overlay", "overlay", "digiworld"])
        used = runner.close_reward_overlay(
            tap=lambda: taps.append(1),
            capture=lambda: None,
            classify=lambda _img: self._Det(next(states)))
        self.assertEqual(used, 3)
        self.assertEqual(len(taps), 3)

    def test_first_tap_can_already_close_it(self):
        used = runner.close_reward_overlay(
            tap=lambda: None,
            capture=lambda: None,
            classify=lambda _img: self._Det("digiworld"))
        self.assertEqual(used, 1)

    def test_gives_up_after_max_taps(self):
        taps = []
        used = runner.close_reward_overlay(
            tap=lambda: taps.append(1),
            capture=lambda: None,
            classify=lambda _img: self._Det("overlay"),
            max_taps=5)
        self.assertEqual(used, 5)
        self.assertEqual(len(taps), 5)


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
        self.assertIn("Muro de pirámides", text)


class PickupBurstTests(unittest.TestCase):
    """Run 20260820T183527: the +20 confetti right after collecting an
    orange splatters 6-9 phantom orange cells across the board for one
    frame (events 32/36/55/159 all show them; the next frame shows zero).
    The flicker guard only caught unexplained DISAPPEARANCES, so the bot
    chased the confetti one step left after nearly every pickup."""

    def test_mass_appearance_is_a_burst(self):
        previous = frozenset({(2, 2)})
        current = frozenset({(0, 2), (1, 2), (2, 1), (3, 0), (3, 2), (4, 0)})
        self.assertTrue(runner.items_bursting(current, previous))

    def test_scroll_reveal_is_not_a_burst(self):
        # One column scrolled in from the right: old items shift left,
        # up to two new cells appear at the right edge.
        previous = frozenset({(1, 3), (3, 2)})
        current = frozenset({(1, 2), (3, 1), (2, 4), (4, 4)})
        self.assertFalse(runner.items_bursting(current, previous))

    def test_single_new_sighting_is_not_a_burst(self):
        previous = frozenset({(1, 3)})
        current = frozenset({(1, 3), (2, 4)})
        self.assertFalse(runner.items_bursting(current, previous))

    def test_empty_previous_frame_is_not_a_burst(self):
        self.assertFalse(runner.items_bursting(frozenset({(1, 1), (2, 2), (3, 3)}),
                                               frozenset()))


class AttackEconomicsTests(unittest.TestCase):
    """Run 20260820T183527 attacks 25/85: a garra route (200 + 40 = 240
    shards) was chosen over a free 4-step detour (160 shards) because the
    pathfinder priced a pyramid at 2 steps. Real price: garra plus the
    follow-up step, minus the expected drop (~1 step), is about 5 steps."""

    def test_free_detour_beats_breaking_through(self):
        # Player (1,1), pyramid (1,2), orange behind it at (1,3); row 2
        # free. Mirrors attack 25: the bot must walk around, not attack.
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(1, 2)]["pyramid"] = 0.9
        info[(1, 3)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertNotEqual(action[0], "attack")

    def test_walled_in_orange_still_gets_the_attack(self):
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(1, 3)].update(item=0.09, orange=0.09)
        for cell in ((0, 2), (1, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (1, 4)):
            info[cell]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertEqual(action[0], "attack")


class ClawMemoryTests(unittest.TestCase):
    """The claw at run 20260820T181916 event 83 was real (user-confirmed)
    but the detector dropped it for one frame and the bot abandoned it.
    Claws only move with the scroll, so a recent sighting is re-injected
    for a few frames to bridge detector gaps."""

    def test_remembered_claw_is_reinjected(self):
        info = empty_grid()
        for values in info.values():
            values["claw"] = 0.0
        merged = runner.merge_remembered_items(
            info, {(2, 2): ("claw", 5)}, (0, 0))
        self.assertGreater(merged[(2, 2)]["claw"], 0.10)
        self.assertLessEqual(merged[(2, 2)]["item"], 0.06)

    def test_remembered_claw_becomes_a_target_again(self):
        info = empty_grid()
        for values in info.values():
            values["claw"] = 0.0
        info[(2, 1)]["player"] = 0.2
        merged = runner.merge_remembered_items(
            info, {(2, 2): ("claw", 5)}, (2, 1))
        action, reason = strategy.choose(merged)
        # The adjacent-item rule may claim it first; what matters is that
        # the bot steps onto the remembered claw instead of dropping it.
        self.assertEqual(action, ("move", (2, 2), "right"))

    def test_claw_memory_expires_quickly(self):
        remembered = {(2, 2): ("claw", 5), (3, 3): ("orange", 5)}
        pruned = runner.prune_remembered_items(remembered, done=10,
                                               player=(0, 0))
        self.assertNotIn((2, 2), pruned)   # claw TTL 4 exceeded
        self.assertIn((3, 3), pruned)      # item TTL 25 still valid

    def test_visited_cell_is_forgotten(self):
        remembered = {(2, 2): ("claw", 9)}
        pruned = runner.prune_remembered_items(remembered, done=10,
                                               player=(2, 2))
        self.assertEqual(pruned, {})


class ScrollAwareRoutingTests(unittest.TestCase):
    """Run 20260820T181916 events 188-192: oranges on row 1, player riding
    row 0 rightward. Every misaligned right step scrolls the target one
    column left without getting closer to picking it; six of them pushed
    two oranges from column 4 into the perishable band. Align the row
    first (vertical steps do not scroll), then ride the scroll."""

    def test_misaligned_right_target_aligns_row_first(self):
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(1, 3)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "move")
        self.assertEqual(action[2], "down")

    def test_same_row_target_still_moves_right(self):
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(1, 3)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[2], "right")

    def test_blocked_target_row_still_rides_the_free_row(self):
        # With the target row walled, the misaligned ride stays the
        # cheapest plan and must survive the alignment penalty.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(1, 4)].update(item=0.09, orange=0.09)
        wall(info, 1, (2, 3))
        action, reason = strategy.choose(info, attacks_enabled=False,
                                         dashes_enabled=False)
        self.assertEqual(action[2], "right")


class CheapDetourTests(unittest.TestCase):
    """Run 20260820T181916 event 83: a borderline single-frame claw at
    (4,0) - three steps away, leftward - triggered a left detour and was
    gone the next frame. Non-orange pickups that need leftward travel are
    only worth a simple detour (Manhattan distance <= 2); at 3+ the step
    cost and the vanish risk beat the pickup's 200-shard value."""

    def claw_at(self, cell):
        info = empty_grid()
        for values in info.values():
            values["claw"] = 0.0
        info[cell]["claw"] = 0.2
        return info

    def test_far_leftward_claw_is_ignored(self):
        info = self.claw_at((4, 0))
        info[(2, 1)]["player"] = 0.2
        action, reason = strategy.choose(info)
        self.assertNotIn("claw targets", reason)

    def test_near_leftward_claw_is_still_chased(self):
        info = self.claw_at((3, 0))
        info[(2, 1)]["player"] = 0.2
        action, reason = strategy.choose(info)
        self.assertIn("claw targets", reason)

    def test_rightward_claw_keeps_any_distance(self):
        info = self.claw_at((4, 3))
        info[(0, 0)]["player"] = 0.2
        action, reason = strategy.choose(info)
        self.assertIn("claw targets", reason)


if __name__ == "__main__":
    unittest.main()
