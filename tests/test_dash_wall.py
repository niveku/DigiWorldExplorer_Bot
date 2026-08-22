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
    def test_wall_still_hunted_past_a_surviving_orange(self):
        # The dash is routing (user directive 2026-08-21b): an orange at
        # column >=3 survives the scroll and ends three columns closer.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 0, (2, 3, 4))
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
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
        # Since the pair-economics gate (run 20260821T225908) a bare
        # pair no longer pays; the right-side orange makes it routing.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(0, 4)].update(item=0.10, orange=0.10)
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
        info[(0, 4)].update(item=0.10, orange=0.10)
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

    def test_surviving_oranges_ride_along_with_the_wall_dash(self):
        # User directive 2026-08-21b (run 220436 n=136): the dash is
        # routing - a column>=3 orange survives the scroll and ends
        # three columns closer, so the wall is hunted first.
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

    def test_pair_waits_for_an_imminent_wall_one_row_away(self):
        # The 033221 lesson holds for a wall the hunt can reach within a
        # frame or two; a farther wall no longer blocks the pair (run
        # 20260821T213642 n=128-132 spent two garras that way).
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        wall(info, 1, (2, 3, 4))
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
        info[(0, 4)].update(item=0.10, orange=0.10)
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

    def test_dying_orb_outranks_a_safe_orange(self):
        # Doctrine flip (run 20260821T225908 n=182-185, user-confirmed
        # loss): the orb at column 1 dies to the next scroll while the
        # column-4 orange survives many - the orb is rescued first.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, green=0.10)
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("urgent pickup"))
        self.assertEqual(action[2], "down")

    def test_a_ticket_does_not_veto_the_pair_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(0, 4)].update(item=0.10, orange=0.10)
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
        self.assertTrue("claw" in reason or
                        reason.startswith("urgent pickup"))

    def test_adjacent_claw_is_grabbed_first(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 1)]["claw"] = 0.15
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (3, 1), "down"))


# ItemsFlickeringTests removed 2026-08-21 with the burst WAIT itself:
# the per-cell suspect filter adjudicates phantoms and the confirmed-item
# memory holds real items through animation frames, so the whole-board
# flicker guard only added 0.4-0.8s of dead time per pickup wave.


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


class WallDashRescueTests(unittest.TestCase):
    """Run 20260820T191232 events 47-53: the bot stood ADJACENT to an
    orange at (4,2), but the wall rule hijacked it two cells up and the
    wall dash's 3-column scroll deleted that orange and the paws at
    (3,2) - about 300 shards of value for a 400-shard dash with zero
    items in its path. The pair dash already defers to at-risk pickups;
    the wall dash and its approach must too. Walls survive the rescue."""

    def wall_board(self):
        info = empty_grid()
        wall(info, 2, (2, 3, 4))
        return info

    def test_wall_dash_defers_to_left_band_pickups(self):
        info = self.wall_board()
        info[(2, 1)]["player"] = 0.2   # standing on the launch cell
        info[(4, 2)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertNotEqual(action[0], "dash")

    def test_wall_approach_defers_to_an_adjacent_orange(self):
        info = self.wall_board()
        info[(4, 1)]["player"] = 0.2
        info[(4, 2)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertEqual(action, ("move", (4, 2), "right"))

    def test_wall_dash_still_fires_with_right_side_pickups(self):
        # A pickup at column 3+ survives the 3-column scroll shifted to
        # column 0 and stays rescuable after the dash. Since the
        # orange-first doctrine the dash arrives via the pair rule (the
        # wall hunt defers to the orange), but it still fires from the
        # launch cell.
        info = self.wall_board()
        info[(2, 1)]["player"] = 0.2
        info[(4, 3)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertEqual(action[0], "dash")


class SuspectAppearanceTests(unittest.TestCase):
    """Items cannot appear mid-board: they scroll in from the right edge
    or get revealed by breaking a pyramid. Anything else is animation
    residue (the +20 confetti painted 6-9 phantom oranges per pickup in
    run 20260820T183527; two ghosts still leaked past the burst WAIT in
    run 20260820T184744 events 105/136). Suspects are excluded from the
    decision for one frame; a real item survives and becomes targetable."""

    def test_mid_board_appearance_is_suspect(self):
        previous = frozenset({(2, 2)})
        current = frozenset({(2, 2), (0, 1), (3, 0)})
        self.assertEqual(runner.suspect_appearances(current, previous, shift=0),
                         {(0, 1), (3, 0)})

    def test_right_edge_arrival_is_legit(self):
        previous = frozenset({(1, 3)})
        current = frozenset({(1, 3), (2, 4)})
        self.assertEqual(runner.suspect_appearances(current, previous, shift=0),
                         set())

    def test_scroll_shift_is_legit(self):
        previous = frozenset({(1, 3), (3, 2)})
        current = frozenset({(1, 2), (3, 1), (4, 4)})
        self.assertEqual(runner.suspect_appearances(current, previous, shift=1),
                         set())

    def test_revealed_drop_at_attacked_cell_is_legit(self):
        previous = frozenset()
        current = frozenset({(2, 2)})
        self.assertEqual(
            runner.suspect_appearances(frozenset({(2, 2)}),
                                       frozenset({(1, 1)}),
                                       shift=0, attack_cell=(2, 2)),
            set())

    def test_first_frame_accepts_everything(self):
        self.assertEqual(
            runner.suspect_appearances(frozenset({(1, 1), (2, 2)}), frozenset(),
                                       shift=0),
            set())

    def test_dash_reveals_are_legit(self):
        # Game invariant (user, 2026-08-21): a dash-broken pyramid can
        # also reveal a collectible; those path cells (shifted 3 by the
        # dash's own scroll) are as legitimate as a garra's target cell.
        previous = frozenset({(2, 4)})
        current = frozenset({(2, 1), (3, 0)})
        self.assertEqual(
            runner.suspect_appearances(current, previous, shift=3,
                                       revealed_cells={(3, 0)}),
            set())
        self.assertEqual(
            runner.suspect_appearances(current, previous, shift=3),
            {(3, 0)})

    def test_survivor_is_no_longer_suspect_next_frame(self):
        previous = frozenset({(2, 2), (0, 1)})
        current = frozenset({(2, 2), (0, 1)})
        self.assertEqual(runner.suspect_appearances(current, previous, shift=0),
                         set())

    def test_two_frame_confetti_stays_suspect(self):
        # Run 20260820T184744 event 136: the confetti starts on the
        # pickup frame itself and survives into the next one, so a
        # 1-frame check saw it as a survivor. A cell that was a fresh
        # suspect last frame and is still visible stays suspect once
        # more - and only once, so real items unlock on frame three.
        fresh_last = {(3, 1)}
        current = frozenset({(3, 1), (2, 4)})
        combined = runner.combined_suspects(
            fresh=set(), previous_fresh=fresh_last, current=current)
        self.assertEqual(combined, {(3, 1)})

    def test_real_item_unlocks_on_frame_three(self):
        # Frame 3: the cell is no longer in previous_fresh (frame 2's
        # fresh set was empty for it) so it becomes targetable.
        combined = runner.combined_suspects(
            fresh=set(), previous_fresh=set(),
            current=frozenset({(3, 1)}))
        self.assertEqual(combined, set())

    def test_wrong_shift_cannot_explain_a_ghost(self):
        # Run 20260820T184744 event 105: with guessed shifts, a shift-1
        # mapping of a real item coincidentally landed on the phantom's
        # cell and the ghost was chased. The board did not scroll between
        # those frames, and shift=0 must expose it.
        previous = frozenset({(1, 1)})
        current = frozenset({(1, 0), (2, 3)})
        self.assertEqual(runner.suspect_appearances(current, previous, shift=0),
                         {(1, 0), (2, 3)})


class RouteThroughPickupTests(unittest.TestCase):
    """Run 20260820T184744 events 194-196: orange at (2,3), paws at
    (2,2), pyramid at (2,1). Both routes to the orange cost the same, and
    the bot rode the empty row 3 instead of crossing the paws. Equal-cost
    ties must prefer the path that collects something on the way."""

    def test_equal_paths_prefer_the_one_with_a_pickup(self):
        info = empty_grid()
        info[(1, 2)].update(item=0.09, orange=0.09)   # goal
        info[(2, 2)].update(item=0.09, pink=0.09)     # paws en route
        step = strategy.shortest_action(info, (2, 1), {(1, 2)})
        self.assertEqual(step[2], "right")

    def test_without_the_pickup_vertical_alignment_wins(self):
        info = empty_grid()
        info[(1, 2)].update(item=0.09, orange=0.09)
        step = strategy.shortest_action(info, (2, 1), {(1, 2)})
        self.assertEqual(step[2], "up")


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

    def test_all_categories_share_one_ttl(self):
        # Game invariant (user, 2026-08-21): no pickup - claws included -
        # ever vanishes except by collection or the left edge, so the
        # old claw-specific 4-frame TTL only recreated the flicker churn
        # the memory exists to prevent. One unified TTL guards against
        # our own coordinate errors.
        remembered = {(2, 2): ("claw", 5), (3, 3): ("orange", 5)}
        pruned = runner.prune_remembered_items(remembered, done=10,
                                               player=(0, 0))
        self.assertIn((2, 2), pruned)
        self.assertIn((3, 3), pruned)
        self.assertEqual(runner.prune_remembered_items(
            remembered, done=31, player=(0, 0)), {})

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
        # Since the mid-tier rescue it may surface as an urgent pickup.
        self.assertTrue("claw targets" in reason or
                        reason.startswith("urgent pickup"))

    def test_rightward_claw_keeps_any_distance(self):
        info = self.claw_at((4, 3))
        info[(0, 0)]["player"] = 0.2
        action, reason = strategy.choose(info)
        self.assertIn("claw targets", reason)


class DashSuspectDeferenceTests(unittest.TestCase):
    """Run 20260821T154754 n=578: the wall dash fired while three
    just-appeared items at (0,1), (0,2) and (1,0) were still one-frame
    suspects; the 3-column scroll deleted all three before the next
    frame could confirm them. A suspect in the left band vetoes both
    dash rules for that single frame: a phantom vanishes and the dash
    fires on the very next pass, a real pickup gets rescued instead."""

    def pair_board(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        # Right-side orange: the pair stays worth its 400 shards under
        # the pair-economics gate.
        info[(1, 4)].update(item=0.09, orange=0.09)
        return info

    def test_wall_dash_defers_to_left_band_suspects(self):
        info = empty_grid()
        wall(info, 2, (2, 3, 4))
        info[(2, 1)]["player"] = 0.2
        action, reason = strategy.choose(info, hunt_walls=True,
                                         ignored_targets={(0, 1)},
                                         suspect_cells={(0, 1)})
        self.assertNotEqual(action[0], "dash")

    def test_pair_dash_defers_to_left_band_suspects(self):
        action, reason = strategy.choose(self.pair_board(),
                                         ignored_targets={(4, 0)},
                                         suspect_cells={(4, 0)})
        self.assertNotEqual(action[0], "dash")

    def test_pair_dash_fires_once_suspects_clear(self):
        action, reason = strategy.choose(self.pair_board())
        self.assertEqual(action[0], "dash")

    def test_right_side_suspects_do_not_veto(self):
        # A suspect at column 3+ survives the 3-column scroll and stays
        # adjudicable after the dash.
        action, reason = strategy.choose(self.pair_board(),
                                         ignored_targets={(0, 4)},
                                         suspect_cells={(0, 4)})
        self.assertEqual(action[0], "dash")

    def test_corridor_dash_defers_to_left_band_suspects(self):
        action = ("attack", (3, 2), "right")
        preview = [False, False, False, True, False]
        self.assertTrue(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True))
        self.assertFalse(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True, suspect_cells={(0, 1)}))
        self.assertTrue(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True, suspect_cells={(0, 4)}))

    def test_committed_wall_dash_defers_to_left_band_suspects(self):
        self.assertTrue(runner.committed_wall_dash(((4, 0), 10), (4, 0), 12))
        self.assertFalse(runner.committed_wall_dash(
            ((4, 0), 10), (4, 0), 12, suspect_cells={(1, 2)}))
        self.assertTrue(runner.committed_wall_dash(
            ((4, 0), 10), (4, 0), 12, suspect_cells={(0, 3)}))


class ExploreBounceBanTests(unittest.TestCase):
    """Run 20260821T154754 n=770-774: the explorer bounced (3,0)<->(4,0)
    for six moves on an empty board before the strike counter banned the
    pocket. A tripped loop guard during goal-less exploration is already
    proof of waste: ban on the first strike, not the third."""

    def test_goalless_explore_loop_bans_immediately(self):
        self.assertTrue(runner.explore_bounce(True, set(), "explore right"))

    def test_visible_goals_keep_the_slow_strikes(self):
        self.assertFalse(runner.explore_bounce(True, {(2, 2)}, "explore right"))

    def test_target_reasons_keep_the_slow_strikes(self):
        self.assertFalse(runner.explore_bounce(
            True, set(), "orange targets=[(0, 1)]"))

    def test_untripped_guard_never_bans(self):
        self.assertFalse(runner.explore_bounce(False, set(), "explore right"))


class SuspectHoldTests(unittest.TestCase):
    """Run 20260821T154754 n=902-904: with every visible pickup still a
    suspect the bot explored away, backtracked, and only then confirmed
    (0,1) as a perishable orange - four moves spent on information a
    single 0.4s hold delivers. When suspects are the only goals on the
    board, hold exactly one frame instead of exploring."""

    def test_holds_one_frame_when_all_goals_are_suspects(self):
        self.assertTrue(runner.should_hold_for_suspects(
            "explore right", {(0, 1)}, {(0, 1)}, holds=0))

    def test_holds_match_the_two_frame_suspicion_window(self):
        # Run 20260821T225908 n=43 (user-spotted): the combined-suspects
        # carryover keeps a fresh cell suspect for TWO frames, but the
        # hold only waited one - so the bot explored away from the real
        # orange after the first hold and had to walk back. The hold now
        # covers the full adjudication window.
        self.assertTrue(runner.should_hold_for_suspects(
            "explore right", {(0, 1)}, {(0, 1)}, holds=1))
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", {(0, 1)}, {(0, 1)}, holds=2))

    def test_a_confirmed_goal_cancels_the_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", {(0, 1), (2, 2)}, {(0, 1)}, holds=0))

    def test_non_explore_reasons_never_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "orange targets=[(1, 1)]", {(0, 1)}, {(0, 1)}, holds=0))

    def test_no_suspects_means_no_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", set(), set(), holds=0))


class ConfirmedItemMemoryTests(unittest.TestCase):
    """Run 20260821T192126: eleven confirmed pickups scrolled off the
    left edge unclaimed. Each flickered for a frame under a pickup
    animation, re-entered as a fresh suspect, and stayed unconfirmable
    forever (44 suspect holds in 500 moves). A pickup cannot vanish from
    the board: it leaves by collection or by the left edge. Confirmed
    (non-suspect) sightings are remembered, so memory bridges the flicker
    and the cell never reads as a fresh arrival again."""

    def test_visible_pickups_are_remembered(self):
        info = empty_grid()
        info[(2, 1)].update(item=0.09, orange=0.09)
        remembered = runner.remember_confirmed_items(
            {}, info, player=(0, 0), suspects=set(), done=7)
        self.assertEqual(remembered[(2, 1)], ("orange", 7))

    def test_suspect_cells_are_not_remembered(self):
        info = empty_grid()
        info[(2, 1)].update(item=0.09, orange=0.09)
        remembered = runner.remember_confirmed_items(
            {}, info, player=(0, 0), suspects={(2, 1)}, done=7)
        self.assertNotIn((2, 1), remembered)

    def test_player_cell_is_not_remembered(self):
        info = empty_grid()
        info[(2, 1)].update(item=0.09, orange=0.09, player=0.2)
        remembered = runner.remember_confirmed_items(
            {}, info, player=(2, 1), suspects=set(), done=7)
        self.assertNotIn((2, 1), remembered)

    def test_still_visible_items_refresh_their_timestamp(self):
        info = empty_grid()
        info[(2, 1)].update(item=0.09, orange=0.09)
        remembered = runner.remember_confirmed_items(
            {(2, 1): ("orange", 2)}, info, player=(0, 0), suspects=set(),
            done=9)
        self.assertEqual(remembered[(2, 1)], ("orange", 9))

    def test_revealed_pickup_enters_memory(self):
        remembered = runner.remember_revealed_pickup(
            {}, {"revealed": "orange", "broken": True}, (2, 2), done=9)
        self.assertEqual(remembered[(2, 2)], ("orange", 9))

    def test_empty_reveal_is_not_remembered(self):
        self.assertEqual(runner.remember_revealed_pickup(
            {}, {"revealed": None, "broken": True}, (2, 2), done=9), {})

    def test_merge_survives_every_economic_category(self):
        # Crash in production (run 20260821T195439): memory now stores
        # economic types, but the merge patch indexed them as if they
        # were grid color masks - KeyError: 'purple_ticket' on frame 12.
        # The patch must write the category's underlying color mask and
        # its discriminator so pickup_type round-trips.
        for category, expect in (("orange", "orange"),
                                 ("steps", "steps"),
                                 ("purple_ticket", "purple_ticket"),
                                 ("dash_orb", "dash_orb"),
                                 ("green_ticket", "green_ticket")):
            with self.subTest(category=category):
                info = empty_grid()
                merged = runner.merge_remembered_items(
                    info, {(2, 1): (category, 5)}, player=(0, 0))
                values = merged[(2, 1)]
                self.assertGreater(values["item"], .06)
                self.assertEqual(strategy.pickup_type(values), expect)


class PairLaunchGateTests(unittest.TestCase):
    """Run 20260821T192126 n=117-121: from (0,0) the pair-launch rule
    approved the step down to (1,0) because the claw at (0,2) sat in the
    CURRENT row's path and was exempt from at_risk; from (1,0) the same
    claw was off-path and vetoed the dash, so the claw rule sent the bot
    straight back up - a two-cell decision loop that burned five moves.
    The launch approach now judges risk against the LAUNCH row's path."""

    def launch_board(self):
        info = empty_grid()
        info[(0, 0)]["player"] = 0.2
        info[(1, 1)]["pyramid"] = 0.9
        info[(1, 2)]["pyramid"] = 0.9
        info[(0, 4)].update(item=0.09, orange=0.09)
        return info

    def test_launch_step_refused_when_launch_path_leaves_a_pickup_at_risk(self):
        info = self.launch_board()
        info[(0, 2)]["claw"] = 0.2
        action, reason = strategy.choose(info)
        # The launch is refused; with the fixture's right-side orange the
        # routing may then name either endangered pickup - what matters
        # is that no launch step fires while the claw sits at risk.
        self.assertFalse(reason.startswith("pair launch"))

    def test_launch_step_still_fires_on_a_clean_board(self):
        action, reason = strategy.choose(self.launch_board())
        self.assertTrue(reason.startswith("pair launch"))

    def test_claw_with_item_score_still_vetoes_the_pair_dash(self):
        # n=122: the claw's item mask crossed .06 for one frame, dropped
        # it out of mid_items, and the pair dash scrolled it off board.
        info = empty_grid()
        info[(2, 0)]["player"] = 0.2
        info[(2, 1)]["pyramid"] = 0.9
        info[(2, 2)]["pyramid"] = 0.9
        info[(0, 2)].update(item=0.09, claw=0.15)
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "dash")


class RememberedSuspectTests(unittest.TestCase):
    """Run 20260821T213642 n=51-56: the dash orb at (4,0) sat in memory
    (confirmed) and in the suspect set (its detection flickered into a
    'fresh arrival' every other frame) at the same time. Suspects are
    fed to choose() as ignored targets, so the confirmed orb was never
    targeted and scrolled off the board. Memory outranks suspicion: a
    remembered cell cannot be a suspect."""

    def test_remembered_cells_are_dropped_from_suspects(self):
        self.assertEqual(
            runner.drop_remembered_suspects(
                {(4, 0), (1, 3)}, {(4, 0): ("dash_orb", 7)}),
            {(1, 3)})

    def test_without_memory_suspects_pass_through(self):
        self.assertEqual(
            runner.drop_remembered_suspects({(4, 0)}, {}), {(4, 0)})


class WallVersusOrangeTests(unittest.TestCase):
    """The dash is ROUTING, not abandonment (user directive 2026-08-21,
    run 220436 n=136: launch one step up, orange at (3,4) - the skipped
    dash would have broken three pyramids AND left the orange three
    columns closer). An orange at column >=3 survives the 3-column
    scroll and gets closer, so it never defers the wall; an orange in
    the left band would be eroded and still does."""

    def wall_board(self):
        info = empty_grid()
        wall(info, 1, (2, 3, 4))
        info[(3, 1)]["player"] = 0.2
        return info

    def test_surviving_orange_does_not_defer_the_wall(self):
        info = self.wall_board()
        info[(3, 4)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertTrue(reason.startswith("approach dash wall"))

    def test_left_band_orange_still_defers_the_wall(self):
        info = self.wall_board()
        info[(3, 0)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertFalse(reason.startswith(("approach dash wall",
                                            "3+ pyramid wall")))

    def test_wall_hunt_resumes_once_oranges_are_gone(self):
        action, reason = strategy.choose(self.wall_board(), hunt_walls=True)
        self.assertTrue(reason.startswith("approach dash wall"))


class UnstableWallPairDashTests(unittest.TestCase):
    """Run 20260821T213642 n=128-132: a pair sat in the player's row and
    a 3-wall elsewhere. The wall was not yet stable (hunt_walls False),
    so it produced no action - but its mere existence still blocked the
    pair dash, and the explorer spent two garras before the dash finally
    fired. A wall that cannot be hunted must not veto the pair."""

    def pair_with_far_wall(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 4)]["pyramid"] = 0.9
        wall(info, 4, (2, 3, 4))
        info[(0, 4)].update(item=0.09, orange=0.09)
        return info

    def test_unstable_wall_does_not_block_the_pair_dash(self):
        action, reason = strategy.choose(self.pair_with_far_wall(),
                                         hunt_walls=False)
        self.assertEqual(action[0], "dash")

    def test_stable_wall_still_outranks_the_pair(self):
        action, reason = strategy.choose(self.pair_with_far_wall(),
                                         hunt_walls=True)
        self.assertNotEqual(action[0], "dash")


class ValueAwareDetourTests(unittest.TestCase):
    """Run 20260821T220436 n=52-62: a dash orb (worth 400 shards, one
    full dash) rode from (4,3) to (4,0) over ten frames and was then
    abandoned because the leftward-detour cap (2 cells, priced for
    200-shard claws) filtered it out; the next explore step scrolled it
    off. The cap now scales with the pickup's value: an orb pays for up
    to five leftward steps."""

    def board_with(self, cell, **scores):
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[cell].update(**scores)
        return info

    def test_distant_leftward_orb_is_chased(self):
        info = self.board_with((4, 0), item=0.09, green=0.09)
        action, reason = strategy.choose(info)
        self.assertIn("targets", reason)

    def test_distant_leftward_claw_is_still_dropped(self):
        info = self.board_with((4, 0), claw=0.2)
        action, reason = strategy.choose(info)
        self.assertNotIn("claw targets", reason)


class ScrolledBanTests(unittest.TestCase):
    """Run 20260821T220436: the loop breaker banned (0,1) at n=159
    during an explore ping-pong; nineteen actions later a REAL orange
    scrolled into that exact cell, sat invisible to the perishable
    rescue, and died off the left edge at n=181. Bans mark board
    content, and the content moves with the scroll - so the bans move
    with it too, and a ban pushed off the left edge retires."""

    def test_bans_shift_left_with_the_scroll(self):
        self.assertEqual(runner.shift_items_left({(0, 1): 30, (2, 3): 40}),
                         {(0, 0): 30, (2, 2): 40})

    def test_ban_history_shifts_and_retires(self):
        self.assertEqual(runner.shift_cells_left({(0, 0), (1, 2)}),
                         {(1, 1)})


class PerishableRoutingTests(unittest.TestCase):
    """Run 20260821T215254 n=197: perishables at (4,0),(4,1) with the
    descent walled off by pyramids at (3,0),(3,1). The router priced the
    5-step right-around cheaper than breaking through - and the very
    first rightward step scrolled both targets off the board. A step
    right ERODES a column<=1 target; no route to the perishable band may
    ever include one. Boxed-in perishables get the garra instead."""

    def boxed_board(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 0)]["pyramid"] = 0.9
        info[(3, 1)]["pyramid"] = 0.9
        info[(4, 0)].update(item=0.09, orange=0.09)
        info[(4, 1)].update(item=0.09, orange=0.09)
        return info

    def test_boxed_perishables_are_broken_into_not_circled(self):
        action, reason = strategy.choose(self.boxed_board())
        self.assertTrue(reason.startswith("orange perishable"))
        self.assertEqual(action[0], "attack")

    def test_route_to_perishables_never_steps_right(self):
        step = strategy.shortest_action(
            self.boxed_board(), (2, 1), {(4, 0), (4, 1)},
            allow_obstacles=False)
        if step is not None:
            self.assertNotEqual(step[2], "right")

    def test_open_descent_still_walks_free(self):
        info = self.boxed_board()
        info[(3, 1)]["pyramid"] = 0.0
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (3, 1), "down"))


# A sweep-order rule (start at the row extreme, collect monotonically)
# was prototyped for run 20260821T222310 n=95-105 and DROPPED: the
# route-through-pickups discount already collects mid-column items en
# route, the candidate tours cost the same, and the observed climb-back
# came from the urgent-perishable interrupt correctly saving a dying
# orange. Adding an ordering layer would be overengineering.


class TourPlanningTests(unittest.TestCase):
    """User directive 2026-08-22: plan the whole collection IN ADVANCE -
    shortest route over all pickups, losing none, erosion counted only
    where it is real (visiting a column-c item kills everything left of
    c-1; that is the entire physics). Urgency emerges from the plan
    instead of interrupting it, and the order is stable frame to frame
    because relative positions survive the scroll."""

    def test_no_risk_means_pure_shortest_route(self):
        # The en-route pickup at (0,2) goes first: total 6 steps vs 9.
        # The old code would have called (4,1) urgent and dived.
        order = strategy.plan_tour((0, 1), [(4, 1), (0, 2)])
        self.assertEqual(order, [(0, 2), (4, 1)])

    def test_real_risk_forces_the_left_item_first(self):
        # Visiting (2,4) first scrolls 3 columns and kills (2,0).
        order = strategy.plan_tour((2, 1), [(2, 4), (2, 0)])
        self.assertEqual(order[0], (2, 0))

    def test_three_item_cluster_avoids_the_climb_back(self):
        # (0,1) then (0,2) then (4,1): 7 steps, all collected. Any
        # order that dives to (4,1) between the top two wastes steps.
        order = strategy.plan_tour((1, 1), [(4, 1), (0, 2), (0, 1)])
        self.assertEqual(order, [(0, 1), (0, 2), (4, 1)])

    def test_impossible_saves_deliver_the_most_items(self):
        # (0,4) and (0,0) cannot both survive any order that starts
        # right; the plan keeps both by going left first - and when a
        # loss is truly unavoidable it maximizes the count.
        order = strategy.plan_tour((0, 1), [(0, 0), (0, 4)])
        self.assertEqual(order[0], (0, 0))

    def test_choose_routes_by_tour_not_by_panic(self):
        # Distant safe orange plus a mid-route one: no urgency label,
        # plain shortest-tour routing.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.09, orange=0.09)
        info[(4, 3)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "move")
        self.assertTrue(reason.startswith("orange"))


class FreeAdjacentGrabTests(unittest.TestCase):
    """Run 20260821T234344 n=9: one step from a paws card, an urgent
    perishable appeared three cells away and hijacked the route. But
    perishables only age on OUR rightward moves - an adjacent grab via
    up/down/left scrolls nothing, so it costs the rescue zero erosion.
    The free grab goes first, urgency included."""

    def test_adjacent_paws_beat_the_urgent_interrupt(self):
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(0, 1)].update(item=0.09, pink=0.09)      # paws, one step up
        info[(4, 1)].update(item=0.09, orange=0.09)    # urgent, three down
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("move", (0, 1), "up"))

    def test_rightward_neighbors_do_not_preempt_urgency(self):
        # A right grab advances the scroll; the rescue stays first.
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(1, 2)].update(item=0.09, pink=0.09)
        info[(4, 0)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith(("orange perishable",
                                           "urgent pickup")))


class PerishableMidTierTests(unittest.TestCase):
    """Run 20260821T225908 n=182-185: a dash orb (400 shards, a full
    dash) reached column 1 while two oranges sat safely at column 4.
    The urgent rescue only covered oranges, so the bot rode right for
    the safe fruit and the orb died off the edge. A mid-tier pickup in
    the perishable band outvalues any single orange and is rescued with
    the same urgency; the right-side oranges survive the detour."""

    def test_left_band_orb_is_rescued_before_safe_right_oranges(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(0, 1)].update(item=0.09, green=0.09)     # dash orb, dying
        info[(3, 4)].update(item=0.09, orange=0.09)    # safe
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith(("orange perishable",
                                           "urgent pickup")))
        self.assertEqual(action[2], "up")

    def test_left_band_orange_still_beats_the_orb_by_distance(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 0)].update(item=0.09, orange=0.09)
        info[(0, 1)].update(item=0.09, green=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "move")
        self.assertIn(action[2], ("left", "up"))


class PairDashEconomicsTests(unittest.TestCase):
    """Run 20260821T225908: nine pair dashes, every one with zero items
    in its path and a free detour available - 3,600 shards for ~100 of
    value each. The pair rule priced itself against two garras (600)
    when the true alternative is the free two-step detour (80). A bare
    two-pyramid pair no longer justifies 400 shards: the pair dash needs
    an item in its path, a third pyramid, or a target to the right it
    genuinely approaches."""

    def bare_pair(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        return info

    def test_bare_pair_with_free_detour_keeps_the_dash(self):
        action, reason = strategy.choose(self.bare_pair())
        self.assertNotEqual(action[0], "dash")

    def test_item_in_path_pays_for_the_dash(self):
        info = self.bare_pair()
        info[(2, 4)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash")

    def test_right_side_target_pays_for_the_dash(self):
        info = self.bare_pair()
        info[(0, 4)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash")

    def test_three_pyramids_pay_for_themselves(self):
        info = self.bare_pair()
        info[(2, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash")


class BoardMotionTests(unittest.TestCase):
    """Run 20260821T222310 frame 11 (user-spotted): the screenshot caught
    the scroll mid-animation - the whole board sat offset from the grid,
    a real energy straddled two cells at the bottom, and the classifier
    saw nothing there. A sudden grid jump IS the motion signal (nine
    board_corrections that run), but the old code swapped in the stale
    rect and classified the moving frame anyway. The user rule: only
    look while the grid is at rest - wait and re-capture instead."""

    def test_matching_rects_are_at_rest(self):
        self.assertFalse(runner.board_in_motion(
            (77, 426, 625, 870), (77, 426, 625, 870)))
        self.assertFalse(runner.board_in_motion(
            (74, 424, 626, 875), (77, 426, 625, 870)))

    def test_a_jumped_rect_means_motion(self):
        self.assertTrue(runner.board_in_motion(
            (77, 491, 625, 980), (77, 426, 625, 870)))

    def test_no_baseline_means_no_verdict(self):
        self.assertFalse(runner.board_in_motion(
            (77, 491, 625, 980), None))


class DashPathMemoryTests(unittest.TestCase):
    """Run 20260821T235432 n=64-65 (user-spotted 'why step back?'): the
    dash collected the orange sitting in its path, but its memory entry
    survived, slid three columns with the dash's own shift, and the bot
    stepped back left to grab the ghost. Everything in a dash's path is
    collected or destroyed: its memory dies with the dash."""

    def test_dash_path_memories_are_forgotten(self):
        remembered = {(1, 3): ("orange", 5), (4, 4): ("orange", 5)}
        cleaned = runner.forget_dash_path(
            remembered, [[1, 2], [1, 3], [1, 4]])
        self.assertEqual(cleaned, {(4, 4): ("orange", 5)})


class AttackNoEffectTests(unittest.TestCase):
    """Run 20260821T235432 n=155: the attack tap was swallowed by the
    game (the pyramid at (4,2) was real and still standing), and the
    no-effect guard read that as a phantom pyramid - garras disabled 25
    actions, and twelve frames later the cornered bot stopped the run.
    One swallowed tap retries naturally; only two consecutive no-effect
    attacks prove the target is phantom."""

    def test_one_no_effect_attack_is_retried(self):
        self.assertFalse(runner.should_disable_attacks(1))

    def test_two_consecutive_no_effects_disable(self):
        self.assertTrue(runner.should_disable_attacks(2))


class ShiftGhostTests(unittest.TestCase):
    """Run 20260821T225908 n=13-14 (user-confirmed: ONE claw on screen,
    two in memory). A scroll tap the game swallowed still counted in our
    shift accounting, so the memory slid the claw to (3,0) while the
    live detection re-recorded it at (3,1) - and after grabbing the real
    one the bot stepped left into the ghost. When a remembered cell is
    undetected but its RIGHT neighbor holds a live detection of the same
    category, the left entry is an over-count ghost and dies."""

    def cell(self, **scores):
        base = {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                "item": 0.0, "pyramid": 0.0, "highlight": 1.0, "claw": 0.0}
        base.update(scores)
        return base

    def board(self, claw_at):
        info = {(r, c): self.cell() for r in range(5) for c in range(5)}
        if claw_at:
            info[claw_at]["claw"] = 0.2
        return info

    def test_ghost_twin_left_of_a_live_detection_dies(self):
        remembered = {(3, 0): ("claw", 5), (3, 1): ("claw", 6)}
        deduped = runner.drop_shift_ghosts(remembered, self.board((3, 1)))
        self.assertEqual(deduped, {(3, 1): ("claw", 6)})

    def test_lone_memory_without_a_right_twin_survives(self):
        remembered = {(3, 0): ("claw", 5)}
        deduped = runner.drop_shift_ghosts(remembered, self.board(None))
        self.assertEqual(deduped, remembered)

    def test_different_categories_are_not_twins(self):
        remembered = {(3, 0): ("orange", 5), (3, 1): ("claw", 6)}
        deduped = runner.drop_shift_ghosts(remembered, self.board((3, 1)))
        self.assertEqual(deduped, remembered)


class PendingRevealTests(unittest.TestCase):
    """Run 20260821T222310 n=4-11, user-confirmed loss: the dash broke
    the pyramid at (1,4); its drop landed at (1,1) after the dash's own
    scroll, but the fall animation delayed detection by 3 frames. The
    reveal whitelist only covered the first post-dash frame, so the real
    energy was flagged suspect, never reached memory, and three explore
    rides scrolled it off the board. Broken-pyramid cells now stay
    whitelisted for several frames and shift with the scroll."""

    def test_reveal_cells_stay_live_for_their_ttl(self):
        pending = runner.remember_pending_reveals({}, [(1, 1), (1, 0)], done=4)
        self.assertEqual(runner.live_reveal_cells(pending, done=7),
                         {(1, 1), (1, 0)})
        self.assertEqual(runner.live_reveal_cells(pending, done=9), set())

    def test_late_appearance_at_a_reveal_cell_is_not_suspect(self):
        pending = runner.remember_pending_reveals({}, [(1, 1)], done=4)
        self.assertEqual(
            runner.suspect_appearances(
                frozenset({(1, 1)}), frozenset({(4, 4)}), shift=0,
                revealed_cells=runner.live_reveal_cells(pending, done=7)),
            set())

    def test_reveal_cells_shift_with_the_scroll(self):
        pending = runner.remember_pending_reveals({}, [(1, 1)], done=4)
        shifted = runner.shift_items_left(pending)
        self.assertEqual(runner.live_reveal_cells(shifted, done=5), {(1, 0)})

    def test_only_broken_pyramid_cells_are_reveal_spots(self):
        # Run 20260822T003047 n=13-16 (user force-stop): the whole dash
        # path was whitelisted, pickup confetti landed on the FREE path
        # cell (2,0), entered memory as a confirmed orange, and the tour
        # dutifully stepped back to collect nothing. A dash drop can
        # only appear where the dash broke a pyramid.
        info = {(2, c): {"pyramid": 0.9 if c == 3 else 0.0, "item": 0.0}
                for c in range(5)}
        cells = runner.dash_reveal_cells(info, [[2, 2], [2, 3], [2, 4]])
        self.assertEqual(cells, [(2, 0)])


class WarmupTests(unittest.TestCase):
    """User rule 2026-08-21: the first screens carry no verifiable
    history, so the opening moves must not blind-batch three taps off a
    single unverified frame (run 20260821T222310 opened with an
    explore x3 - two scrolls - before any memory existed)."""

    def test_first_actions_move_one_cell_at_a_time(self):
        self.assertEqual(runner.warmup_batch_limit(0, 3), 1)
        self.assertEqual(runner.warmup_batch_limit(2, 3), 1)

    def test_after_warmup_the_planned_limit_returns(self):
        self.assertEqual(runner.warmup_batch_limit(3, 3), 3)
        self.assertEqual(runner.warmup_batch_limit(10, 2), 2)


class SilentRejectionTests(unittest.TestCase):
    """Run 20260821T222310 n=124/129: 'cannot move there' toasts are
    invisible since the confetti gate (they do not degrade board
    detection), so rejections must be caught by POSITION: a confidently
    seen player still standing on the pre-move cell after a non-scroll
    move means the game refused it."""

    def test_stuck_confident_player_is_a_rejection(self):
        self.assertTrue(runner.silent_rejection(
            "move", (2, 1), (2, 1), (1, 1), "vision", 0.20))

    def test_a_player_that_moved_is_not_stuck(self):
        self.assertFalse(runner.silent_rejection(
            "move", (2, 1), (1, 1), (1, 1), "vision", 0.20))

    def test_scroll_rides_cannot_be_judged(self):
        # Riding right leaves the player on the same screen cell by
        # design: dest == rollback == player proves nothing.
        self.assertFalse(runner.silent_rejection(
            "move", (2, 1), (2, 1), (2, 1), "vision", 0.20))

    def test_weak_or_inferred_positions_prove_nothing(self):
        self.assertFalse(runner.silent_rejection(
            "move", (2, 1), (2, 1), (1, 1), "memory", 0.30))
        self.assertFalse(runner.silent_rejection(
            "move", (2, 1), (2, 1), (1, 1), "vision", 0.05))

    def test_non_moves_never_reject(self):
        self.assertFalse(runner.silent_rejection(
            "attack", (2, 1), (2, 1), (1, 1), "vision", 0.20))
        self.assertFalse(runner.silent_rejection(
            "move", None, (2, 1), (1, 1), "vision", 0.20))


class CuriousExplorerTests(unittest.TestCase):
    """Eight explore-pocket loop bans in run 20260821T222310: with an
    empty board and a blocked lane the explorer dithers between equally
    boring vertical moves. Curiosity (user idea 2026-08-21): prefer the
    row whose right side holds more pyramids - each pair there is a
    potential dash."""

    def blocked_lane(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        return info

    def test_explorer_descends_toward_a_pyramid_pair(self):
        info = self.blocked_lane()
        info[(3, 2)]["pyramid"] = 0.9
        info[(3, 3)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertEqual((action[0], action[2]), ("move", "down"))

    def test_explorer_climbs_toward_a_pyramid_pair(self):
        info = self.blocked_lane()
        info[(1, 2)]["pyramid"] = 0.9
        info[(1, 3)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dashes_enabled=False)
        self.assertEqual((action[0], action[2]), ("move", "up"))


class RouteHysteresisTests(unittest.TestCase):
    """Detection noise flips equal-cost routes frame to frame (run
    20260821T213642 n=32-34 bounced between the up-around and the
    down-around of the same pyramid). On a cost tie the first step that
    continues the previous direction wins, so a replan under noise keeps
    walking the same way instead of alternating."""

    def detour_board(self):
        # Target 2 right, direct path blocked: up-around and down-around
        # tie exactly.
        info = empty_grid()
        info[(2, 0)]["player"] = 0.2
        info[(2, 1)]["pyramid"] = 0.9
        info[(2, 2)].update(item=0.09, orange=0.09)
        return info

    def test_tie_follows_previous_direction_down(self):
        step = strategy.shortest_action(
            self.detour_board(), (2, 0), {(2, 2)}, allow_obstacles=False,
            prefer_direction="down")
        self.assertEqual(step[2], "down")

    def test_tie_follows_previous_direction_up(self):
        step = strategy.shortest_action(
            self.detour_board(), (2, 0), {(2, 2)}, allow_obstacles=False,
            prefer_direction="up")
        self.assertEqual(step[2], "up")


class UnknownOverlayDismissTests(unittest.TestCase):
    """Run 20260821T173052: the Stage Failed 'Growth Guide' panel covered
    the board, five unreliable-board waits ran out, and the run died with
    the panel still open - one tap outside its frame closes it (user
    confirmed). Before giving up, the wait loop now taps the left margin
    (outside any centered dialog) on the 2nd and 4th strike."""

    def test_dismiss_fires_on_second_and_fourth_strike(self):
        self.assertFalse(runner.dismiss_tap_due(1))
        self.assertTrue(runner.dismiss_tap_due(2))
        self.assertFalse(runner.dismiss_tap_due(3))
        self.assertTrue(runner.dismiss_tap_due(4))
        self.assertFalse(runner.dismiss_tap_due(5))

    def test_dismiss_point_sits_outside_centered_dialogs(self):
        x, y = runner.DISMISS_TAP_XY
        self.assertLess(x, 60)          # left of any dialog frame
        self.assertTrue(300 <= y <= 900)  # away from HUD top and bottom bars


if __name__ == "__main__":
    unittest.main()
