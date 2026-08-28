import unittest

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner
import world_model


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


class ReverseStepVetoTests(unittest.TestCase):
    """A step back onto the cell you just left cannot pay for itself.

    Run 20260823T143257 n=45-52 alternated (1,1) up -> (0,1) down -> (1,1)
    for eight frames on a board that never changed: from row 1 the orange
    at (0,3) won, from row 0 the dash-pair launch at (1,1) won, and each
    goal lives in a different branch of choose() so the explorer's own
    -30 reversal penalty never saw them. Six paws burned for zero
    progress.

    The law is physical, not a heuristic: a charged step that collected
    nothing and did not scroll leaves the board byte-identical, so
    returning to the previous cell re-enters a state already judged. The
    runner reports that case as blocked_direction and choose() must route
    around it - but only while an alternative exists.
    """

    def _livelock_board(self, player):
        info = empty_grid()
        info[player]["player"] = 0.5
        for cell in ((1, 2), (1, 3), (3, 1)):
            info[cell]["pyramid"] = 0.9
        info[(0, 3)].update(item=0.10, orange=0.10)
        # The pair launch below is what makes the bot step down here, and
        # since 2026-08-28 it needs a payload on the LAUNCH row. Without
        # this the fixture stops reproducing the livelock and the guard
        # test below says so - which is how this was noticed.
        info[(1, 4)].update(item=0.10, orange=0.10)
        return info

    def test_the_livelock_reversal_is_refused(self):
        info = self._livelock_board((0, 1))
        action, _ = strategy.choose(info, player=(0, 1),
                                    blocked_direction="down")
        self.assertNotEqual(action[2], "down")

    def test_without_the_veto_the_livelock_still_reproduces(self):
        # Guards the fixture: if the strategy ever stops choosing "down"
        # here on its own, this test has stopped proving anything.
        info = self._livelock_board((0, 1))
        action, _ = strategy.choose(info, player=(0, 1))
        self.assertEqual(action[2], "down")

    def test_a_veto_never_strands_the_player(self):
        # Boxed in by pyramids on three sides: the only way out is back.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.5
        for cell in ((1, 1), (3, 1), (2, 2)):
            info[cell]["pyramid"] = 0.9
        action, _ = strategy.choose(info, player=(2, 1),
                                    blocked_direction="left")
        self.assertIsNotNone(action)

    def test_the_detour_never_costs_more_than_the_back_step(self):
        # (4,1) with pyramids at (3,2) and (4,2): closing the way back
        # leaves a garra at (4,2) as the best answer. A wasted paw is 40
        # shards, a garra is 200 - the veto must not "save" the cheap
        # mistake by buying the expensive one.
        info = empty_grid()
        info[(4, 1)]["player"] = 0.5
        for cell in ((0, 1), (3, 2), (4, 2)):
            info[cell]["pyramid"] = 0.9
        action, _ = strategy.choose(info, player=(4, 1),
                                    blocked_direction="up")
        self.assertEqual(action[0], "move")

    def test_an_unrelated_direction_is_untouched(self):
        info = self._livelock_board((0, 1))
        free, _ = strategy.choose(info, player=(0, 1))
        vetoed, _ = strategy.choose(info, player=(0, 1),
                                    blocked_direction="up")
        self.assertEqual(free, vetoed)


class CuriosityNeedsARealPairTests(unittest.TestCase):
    """The vertical tie-break may only pay for a dash that exists.

    The explorer added +6 per obstacle sitting anywhere in columns 2-4 of
    the destination row, but a dash needs TWO in the path - the same
    threshold the pair-launch rule enforces. Run 20260823T151854 n=13-15
    climbed from (1,1) to (0,1) because row 0 held one pyramid at (0,2),
    found its way forward blocked by that very pyramid, and walked back
    down through (1,1) to (2,1), whose (2,2) was free the whole time.
    Three paws to arrive where a single step down would have put it.
    """

    def test_a_lone_pyramid_ahead_does_not_buy_the_climb(self):
        info = empty_grid()
        info[(1, 1)]["player"] = 0.5
        for cell in ((0, 2), (1, 2), (2, 0), (4, 3)):
            info[cell]["pyramid"] = 0.9
        action, _ = strategy.choose(info, player=(1, 1))
        self.assertEqual(action[2], "down")

    def test_a_real_pair_ahead_still_buys_the_step(self):
        info = empty_grid()
        info[(1, 1)]["player"] = 0.5
        for cell in ((0, 2), (0, 3), (1, 2)):
            info[cell]["pyramid"] = 0.9
        action, _ = strategy.choose(info, player=(1, 1))
        self.assertEqual(action[2], "up")


class VerticalStepPrefersAFreeLaneTests(unittest.TestCase):
    """Do not step into a row that cannot go forward either.

    With the way right blocked, the explorer picks a vertical step to
    find a lane - but "down" simply outbid "up" by its base score (12 vs
    10), with no reference to whether the destination row could advance.
    Run 20260823T153436 n=3-5 stood on (3,1) walled by (3,2), stepped
    DOWN to (4,1) walled by (4,2), and came straight back up: two paws
    to learn what the board already showed. The same shape cost two more
    paws at n=29-30 of 20260823T151420.

    The correction is a tie-break, not a goal: it moves a boring lane by
    8 points and never outbids an item, a wall or a dash.
    """

    def test_the_free_lane_wins_over_the_blocked_one(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.5
        for cell in ((3, 2), (4, 2)):
            info[cell]["pyramid"] = 0.9
        action, _ = strategy.choose(info, player=(3, 1))
        self.assertEqual(action[2], "up")

    def test_it_does_not_outbid_a_pickup(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.5
        for cell in ((3, 2), (2, 2)):
            info[cell]["pyramid"] = 0.9
        info[(4, 1)].update(item=0.10, orange=0.10)
        action, _ = strategy.choose(info, player=(3, 1))
        self.assertEqual(action[1], (4, 1))

    def test_a_plain_right_still_beats_any_vertical(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.5
        action, _ = strategy.choose(info, player=(2, 1))
        self.assertEqual(action[2], "right")


class PhantomObstacleHidesEveryPickupChannelTests(unittest.TestCase):
    """A cell that reads as an obstacle cannot also read as a pickup.

    merge_phantom_obstacles zeroed "item" and left "orange" (and the
    other channels) untouched, so a cell merged as a covered pyramid
    stayed in choose()'s orange_items and the adjacent-pickup rule
    walked straight at it. The tap gate then refused the move as a
    pyramid: 13 wasted frames across seven runs on 2026-08-23, three of
    them the same cell (3,1) in run 20260823T154134.
    """

    def board(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.5
        info[(3, 1)].update(item=0.10, orange=0.10)
        return info

    def test_the_planner_stops_seeing_a_pickup_there(self):
        info = runner.merge_phantom_obstacles(self.board(), {(3, 1): 9}, 0)
        action, _ = strategy.choose(info, player=(2, 1))
        self.assertNotEqual(tuple(action[1]), (3, 1))

    def test_the_tap_gate_and_the_planner_now_agree(self):
        info = runner.merge_phantom_obstacles(self.board(), {(3, 1): 9}, 0)
        action, _ = strategy.choose(info, player=(2, 1))
        if action[0] == "move":
            self.assertFalse(runner.unsafe_move_tap(info, tuple(action[1])))

    def test_an_expired_obstacle_leaves_the_pickup_alone(self):
        info = runner.merge_phantom_obstacles(self.board(), {(3, 1): 0}, 5)
        action, _ = strategy.choose(info, player=(2, 1))
        self.assertEqual(tuple(action[1]), (3, 1))


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
        # pair no longer pays; the orange IN THE LANE makes it routing.
        # It used to sit at (0,4), off the dash's row, where nothing
        # counts it - the dash fired on the stock gate instead.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        info[(2, 4)].update(item=0.10, orange=0.10)
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
        # The wall is a real three so the dash is worth firing at all;
        # what is under test is that the far-right orb does not veto it.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3, 4))
        info[(4, 4)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        self.assertEqual(action, ("dash", (2, 1), "right"))

    def test_single_pyramid_in_path_is_not_enough(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2,))
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "dash")

    def test_preview_never_manufactures_a_pair_from_a_lawful_column(self):
        # The old 'preview supplies the second pyramid' case needed the
        # digi in column 2, which the game forbids (it is pinned to
        # columns 0-1). From a lawful column the preview column is four
        # cells away - out of the dash's three - so one real pyramid
        # plus a promise is not a pair. Walls keep their own preview
        # extension, which a launch in column 1 can reach.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (4,))
        preview = [False, False, True, False, False]
        action, reason = strategy.choose(info, preview=preview,
                                         dash_stock=20)
        self.assertNotEqual(action[0], "dash")

    def test_off_row_pickup_does_not_pay_for_a_preview_pair(self):
        info = empty_grid()
        info[(2, 2)]["player"] = 0.2
        wall(info, 2, (4,))
        info[(0, 4)].update(item=0.10, orange=0.10)
        preview = [False, False, True, False, False]
        action, reason = strategy.choose(info, preview=preview)
        self.assertNotEqual(action[0], "dash")

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

    def test_standing_start_with_three_real_pyramids_never_walks_away(self):
        # Run 20260822T175424 n=11-13 (user: 'estaba TOTALMENTE de
        # frente a tres pirámides y decidió devolverse un paso').
        # Pixel forensics cleared the vision: Gatomon scores pyramid
        # 0.14-0.20 vs 0.88-0.99 for real pyramids - the "pyramid" in
        # the player's cell was a PHANTOM obstacle minted by a false
        # (late-tap) rejection. Whatever poisons that cell, the rule
        # holds: if the standing path already reaches three real
        # pyramids, dash NOW - never walk to a computed launch.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(0, 1)]["pyramid"] = 0.9   # sprite misread as pyramid
        wall(info, 0, (2, 3, 4))
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertEqual(action, ("dash", (0, 1), "right"))

    def test_own_row_preview_wall_does_not_block_the_pair(self):
        # Run 20260822T142042 n=452-458: pair launch sent the bot to
        # (2,1); there the pair dash was vetoed because the sixth-column
        # preview graded its own two pyramids into an "imminent wall"
        # whose launch sat one column right. The wall IS the pair -
        # vetoing it let the tour walk off toward (4,4) and the
        # stabilized hunt dragged the bot back: five wasted moves.
        # A wall in the player's own row never blocks the pair; only a
        # wall one row above or below defers it.
        # Payload made real 2026-08-28: this scenario used an
        # OFF-ROW pickup, which right_targets never counted (it
        # requires the target's row to be the dash's), so the dash
        # only fired through the bare-pair stock gate that the
        # dash_result records refuted. The thing under test is
        # unchanged; the payload now is one.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3))
        # Two columns out, so the one-step grab does not answer first.
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(
            info, hunt_walls=False,
            preview=[False, False, True, False, False])
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
        # Payload made real 2026-08-28: this scenario used an
        # OFF-ROW pickup, which right_targets never counted (it
        # requires the target's row to be the dash's), so the dash
        # only fired through the bare-pair stock gate that the
        # dash_result records refuted. The thing under test is
        # unchanged; the payload now is one.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 3, (2, 3))
        info[(3, 4)].update(item=0.10, orange=0.10)
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
        # Column 1 is no longer labeled an emergency (doctrine
        # 2026-08-22) but the tour physics still rescue the orb first:
        # visiting the orange would scroll it off the board.
        self.assertTrue(reason.startswith("dash_orb"))
        self.assertEqual(action[2], "down")

    def test_a_ticket_does_not_veto_the_pair_dash(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3, 4))
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

    def test_orange_stays_in_the_plan_alongside_the_claw(self):
        # The tour orders by route, not by rank: the claw at (2,3) is
        # en route to the orange at (4,3), so it goes first and the
        # orange stays in the plan. (The old assertion pinned the label
        # "orange", which printed whenever ANY orange existed - that
        # label lie is what the mid-tier labeling fix removed.)
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)]["claw"] = 0.15
        info[(4, 3)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("targets", reason)
        self.assertIn("(4, 3)", reason)

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

    def test_mid_tier_label_names_the_actual_pickup(self):
        # Run 20260822T142042 n=499: the tour chased a steps card at
        # (3,4) and the log said "claw targets" - the user read it as a
        # garra spent on nothing. Every mid-tier pickup was labeled
        # "claw"; the label now names the real category.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 4)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("steps targets", reason)


class DashSuspectDeferenceTests(unittest.TestCase):
    """A dash defers to what the left band really holds, not to doubt.

    The two tests that demanded deference to a mere SUSPECT retired
    2026-08-23. They came from run 20260821T154754 n=578 (a wall dash
    scrolled three just-appeared items to their death, all three real)
    under the old suspicion stack, where anything freshly seen was
    suspect for two frames. The world model classifies by ORIGIN
    instead: an item entering at the right edge is explained and
    believed on sight, so what remains suspect is an unexplained birth -
    which is what confetti is. Holding a 400-shard wall-clearing dash
    hostage to a probable phantom cost run 20260823T074036 three paws at
    n=154-157 and three more at n=80-83, walking off the launch cell and
    back. What replaces it: BELIEVED left-band pickups still veto, both
    here (they are in orange_items/mid_items) and in the runner's
    left_band_risk, which every dash rule honours.
    """

    def pair_board(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        # An orange IN THE PATH: the one payload the measurements
        # support. A dash collects what already lies in its lane (n=33,
        # +108.5 energy) and not what its breaks drop (n=427, +12.9).
        info[(2, 4)].update(item=0.09, orange=0.09)
        return info

    def test_a_believed_left_band_pickup_still_vetoes_the_wall_dash(self):
        info = empty_grid()
        wall(info, 2, (2, 3, 4))
        info[(2, 1)]["player"] = 0.2
        info[(0, 1)].update(item=0.16, orange=0.16)
        action, reason = strategy.choose(info, hunt_walls=True)
        self.assertNotEqual(action[0], "dash", reason)

    def test_a_mere_suspect_does_not_hold_the_wall_dash(self):
        info = empty_grid()
        wall(info, 2, (2, 3, 4))
        info[(2, 1)]["player"] = 0.2
        action, reason = strategy.choose(info, hunt_walls=True,
                                         ignored_targets={(0, 1)},
                                         suspect_cells={(0, 1)})
        self.assertEqual(action[0], "dash", reason)

    def test_a_mere_suspect_does_not_hold_the_pair_dash(self):
        action, reason = strategy.choose(self.pair_board(),
                                         ignored_targets={(4, 0)},
                                         suspect_cells={(4, 0)})
        self.assertEqual(action[0], "dash", reason)

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

    def test_the_runner_overrides_defer_to_believed_left_band_pickups(self):
        # left_band_risk carries the BELIEVED pickups. The suspect half
        # of these two vetoes (_left_band_suspects) retired 2026-08-23
        # with the strategy's suspect_risk, for the same reason: it held
        # a wall-clearing dash hostage to probable confetti and cost six
        # paws of dithering in run 20260823T074036.
        action = ("attack", (3, 2), "right")
        preview = [False, False, False, True, False]
        self.assertTrue(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True))
        self.assertFalse(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True, left_band_risk=True))
        self.assertTrue(runner.committed_wall_dash(((4, 0), 10), (4, 0), 12))
        self.assertFalse(runner.committed_wall_dash(
            ((4, 0), 10), (4, 0), 12, left_band_risk=True))

    def test_a_mere_suspect_no_longer_holds_the_runner_overrides(self):
        action = ("attack", (3, 2), "right")
        preview = [False, False, False, True, False]
        self.assertTrue(runner.corridor_dash_due(
            action, (3, 84), 86, preview, True, suspect_cells={(0, 1)}))
        self.assertTrue(runner.committed_wall_dash(
            ((4, 0), 10), (4, 0), 12, suspect_cells={(1, 2)}))


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
    board, hold exactly one frame instead of exploring.

    Since the known-world doctrine (2026-08-22), only RIGHT-band
    suspects (columns 3-4, real ingestion doubt) justify the hold:
    left-band suspects are confetti that can never be believed or
    targeted, so waiting on them was pure lag (run 20260822T174628:
    22 of 58 frames were WAITs, mostly post-pickup confetti)."""

    def test_holds_one_frame_when_all_goals_are_suspects(self):
        self.assertTrue(runner.should_hold_for_suspects(
            "explore right", {(0, 3)}, {(0, 3)}, holds=0))

    def test_holds_match_the_two_frame_suspicion_window(self):
        # Run 20260821T225908 n=43 (user-spotted): the combined-suspects
        # carryover keeps a fresh cell suspect for TWO frames, but the
        # hold only waited one - so the bot explored away from the real
        # orange after the first hold and had to walk back. The hold now
        # covers the full adjudication window.
        self.assertTrue(runner.should_hold_for_suspects(
            "explore right", {(0, 3)}, {(0, 3)}, holds=1))
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", {(0, 3)}, {(0, 3)}, holds=2))

    def test_a_confirmed_goal_cancels_the_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", {(0, 1), (2, 2)}, {(0, 1)}, holds=0))

    def test_non_explore_reasons_never_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "orange targets=[(1, 1)]", {(0, 1)}, {(0, 1)}, holds=0))

    def test_no_suspects_means_no_hold(self):
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", set(), set(), holds=0))


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
        # On the LAUNCH row, past its path: the payload the launch gate
        # now asks for. It used to sit at (0,4) - the player's row - and
        # the gate read right_targets, which is about the player's row,
        # so it justified climbing away from the very target it named
        # (fixed 2026-08-28 after run 20260822T215547 n=27-28).
        info[(1, 4)].update(item=0.09, orange=0.09)
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
        # In the lane, between the two pyramids: the payload the dash is
        # measured to actually collect.
        info[(2, 3)].update(item=0.09, orange=0.09)
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
        self.assertTrue(reason.startswith("orange"))
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


class MidTierDetourCapTests(unittest.TestCase):
    """Paticas ROI (user question 2026-08-22, measured over 275
    counter intervals): one move consumes ~1 patica and a steps card
    returns ~3-5, so a card only pays for about three extra steps of
    detour. A claw refunds a 200-shard garra (~5 steps) and a dash orb
    a 400-shard dash (~10). Oranges are never capped - one orange is
    worth a dash's whole yield. Run 20260822T142042 planned steps
    cards exactly like oranges, detour price unchecked."""

    def test_far_vertical_steps_card_is_dropped_from_the_tour(self):
        # Rightward cards ride the cheap_detour filter for free no
        # matter the vertical cost: the card at (4,2) adds 8 extra
        # steps to the orange route for a ~4-patica refund. Dropped.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(0, 4)].update(item=0.10, orange=0.10)
        info[(4, 2)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("(0, 4)", reason)
        self.assertNotIn("(4, 2)", reason)

    def test_near_steps_card_rides_along(self):
        # Card at (1,2) is 2 extra steps on the way to the orange.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(0, 4)].update(item=0.10, orange=0.10)
        info[(1, 2)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("(1, 2)", reason)

    def test_no_garra_is_spent_to_reach_a_mid_card(self):
        # Run 20260822T142042 n=82: a 200-shard garra broke the
        # pyramid at (3,1) to reach the steps card at (4,1), a
        # 130-200 shard refund. Only oranges justify attack routing;
        # a blocked card wants the free way around or nothing.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, pink=0.10)
        info[(3, 1)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "attack")

    def test_no_garra_is_spent_to_reach_a_ticket(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, pink=0.10, white=0.10)
        info[(3, 1)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "attack")

    def test_steps_card_does_not_veto_a_worthy_pair_dash(self):
        # A left-band steps card (~130 shards) protected from a
        # 400-shard dash whose measured yield is ~+20E: the veto cost
        # more than the card. Claws and orbs (real charge refunds)
        # still veto; oranges always do.
        # Payload made real 2026-08-28: this scenario used an
        # OFF-ROW pickup, which right_targets never counted (it
        # requires the target's row to be the dash's), so the dash
        # only fired through the bare-pair stock gate that the
        # dash_result records refuted. The thing under test is
        # unchanged; the payload now is one.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        wall(info, 2, (2, 3, 4))
        info[(4, 1)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info, hunt_walls=False)
        self.assertEqual(action, ("dash", (2, 1), "right"))

    def test_blocked_path_counts_at_its_real_walking_cost(self):
        # Run 20260822T153206 n=52-56: the steps card at (0,1) sat 3
        # Manhattan steps away (inside the allowance) but the pyramid
        # at (2,1) forced a 5-step walk around - 5 paticas spent for a
        # +4 card. The pruner charges the real walk now.
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(0, 1)].update(item=0.10, pink=0.10)
        info[(2, 1)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertNotIn("(0, 1)", reason)

    def test_unblocked_same_distance_card_is_still_collected(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(0, 1)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("(0, 1)", reason)

    def test_dash_orb_earns_a_longer_detour(self):
        kept = strategy.prune_low_value_mids(
            (2, 1), set(), {(4, 0)}, {(4, 0): "dash_orb"})
        self.assertEqual(kept, {(4, 0)})

    def test_lone_far_steps_card_is_not_worth_the_walk(self):
        kept = strategy.prune_low_value_mids(
            (0, 1), set(), {(4, 0)}, {(4, 0): "steps"})
        self.assertEqual(kept, set())

    def test_orange_is_never_pruned(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 4)].update(item=0.10, orange=0.10)
        info[(4, 0)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertIn("(4, 0)", reason)
        self.assertIn("(2, 4)", reason)


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
        # Column 1 lost its emergency label (doctrine 2026-08-22); the
        # tour still rescues the orb first because any other order
        # scrolls it off the board.
        self.assertTrue(reason.startswith("dash_orb"))
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
    """What actually pays for a 400-shard dash.

    The doctrine this class used to assert - "two REAL pyramids pay for
    the dash on their own, each break drops at ~46% and the dash
    collects the drops in the same motion" - was refuted on 2026-08-28
    by the runner's own dash_result records (n=556): a bare pair yields
    +12.9 energy and a bare three +20.7, both indistinguishable from the
    passive tick, while a pair with an item already in its lane yields
    +108.5. The dash collects what is lying there; it does not collect
    what it breaks.

    So the payload rule is back to what it was before: an item in the
    path, a same-row target the dash's own break opens the lane to, or a
    third pyramid. Advance alone never pays - three columns cost three
    steps (120 shards) on foot against 400."""

    def bare_pair(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        return info

    def test_two_real_pyramids_do_not_pay_for_the_dash(self):
        action, reason = strategy.choose(self.bare_pair())
        self.assertNotEqual(action[0], "dash", reason)

    def test_preview_supplied_pair_still_needs_a_payload(self):
        info = empty_grid()
        info[(2, 2)]["player"] = 0.2
        wall(info, 2, (4,))
        preview = [False, False, True, False, False]
        action, reason = strategy.choose(info, preview=preview)
        self.assertNotEqual(action[0], "dash")

    def test_item_in_path_pays_for_the_dash(self):
        info = self.bare_pair()
        info[(2, 4)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash")

    def test_right_side_target_pays_for_the_dash(self):
        # From column 0 the lane is (2,1)-(2,3), so a same-row target at
        # (2,4) is OUTSIDE the path: this is right_targets on its own,
        # not path_items wearing its name. The old version of this test
        # put the target at (0,4), a different row, which right_targets
        # never counted - it passed on the stock gate instead.
        info = empty_grid()
        info[(2, 0)]["player"] = 0.2
        info[(2, 1)]["pyramid"] = 0.9
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 4)].update(item=0.09, orange=0.09)
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash", reason)

    def test_three_pyramids_pay_for_themselves(self):
        info = self.bare_pair()
        info[(2, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertEqual(action[0], "dash")


class DetectedPickupOnlyTests(unittest.TestCase):
    """Review 2026-08-22 ('suspects' lens): the pickup tally and the
    confetti-source log were read from the MEMORY-MERGED board, so
    stepping onto a stale remembered cell minted a phantom pickup - it
    inflated the run stats and, worse, opened a confetti burst zone
    around a place where nothing was ever collected, suspecting the
    real items around it. Vision decides what was picked up; memory is
    for routing."""

    def test_remembered_only_cell_is_not_a_pickup(self):
        detected = empty_grid()
        merged = empty_grid()
        merged[(2, 1)].update(item=0.16, orange=0.16)
        self.assertIsNone(runner.confirmed_pickup(detected, merged, (2, 1)))

    def test_detected_cell_is_a_pickup(self):
        detected = empty_grid()
        detected[(2, 1)].update(item=0.16, orange=0.16)
        self.assertEqual(
            runner.confirmed_pickup(detected, detected, (2, 1)), "orange")


class StableBoardTests(unittest.TestCase):
    """The board rectangle is physically FIXED on screen - only its
    contents scroll - yet the detector returned a different rectangle
    every single frame (14 frames, 14 rectangles, 4 to 8 px of jitter).
    The derived scroll strips then had different SHAPES, so
    measure_scroll_px bailed out in 74-85% of frames: the pixel sensor
    the whole 'reconcile by MEASURING, not by counting taps' doctrine
    rests on was inert most of the time, and the runner was silently
    trusting the very tap count it was built to distrust.

    Locking the rectangle while detections stay close cuts that to
    10-16% (measured on runs 20260822T234822 and 20260823T033159)."""

    def test_jitter_keeps_the_locked_rectangle(self):
        lock = runner.StableBoard()
        first = lock.settle((73, 424, 623, 872))
        self.assertEqual(first, (73, 424, 623, 872))
        self.assertEqual(lock.settle((76, 426, 622, 868)), first)
        self.assertEqual(lock.settle((77, 425, 626, 874)), first)

    def test_a_real_move_adopts_the_new_rectangle(self):
        lock = runner.StableBoard()
        lock.settle((73, 424, 623, 872))
        moved = (73, 500, 623, 948)          # board genuinely elsewhere
        self.assertEqual(lock.settle(moved), moved)

    def test_none_detection_keeps_the_lock(self):
        lock = runner.StableBoard()
        lock.settle((73, 424, 623, 872))
        self.assertEqual(lock.settle(None), (73, 424, 623, 872))


class SensorConfidenceTests(unittest.TestCase):
    """Review 2026-08-22 ('physics' lens): measure_scroll_px took the
    argmin of the strip alignment with no confidence margin, then
    destructively rewrote every board-memory structure with it. On a
    low-contrast strip (an empty right band) the scores at 0, 1 and 2
    columns sit within noise of each other and the winner is arbitrary.
    None already means 'trust the tap count', which is the safe answer
    when the picture cannot decide."""

    def test_flat_strip_refuses_to_measure(self):
        import numpy as np
        flat = np.zeros((20, 90), dtype=np.uint8)
        cols, sliding = runner.measure_scroll_px(flat, flat.copy())
        self.assertIsNone(cols)

    def test_clear_shift_still_measures(self):
        import numpy as np
        rng = np.random.default_rng(7)
        prev = rng.integers(0, 255, (20, 90), dtype=np.uint8)
        cur = np.roll(prev, -30, axis=1)
        cols, sliding = runner.measure_scroll_px(prev, cur)
        self.assertEqual(cols, 1)


class RightTargetPayloadTests(unittest.TestCase):
    """Review 2026-08-22 ('economy' lens): right_targets made ANY
    pickup at column >= 3, on any row, count as payload - so every
    two-pyramid pair fired regardless of the stock gate and of the
    preview-needs-payload rule, which is most of the time. The
    economics do not hold: three columns of pure advance cost three
    steps (120 shards) on foot against 400 for the dash. Advance is
    only worth the dash when the dash's own break opens the lane to
    that target - i.e. the target sits in the row the dash runs."""

    def _pair(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        return info

    def test_off_row_right_pickup_is_not_payload(self):
        info = self._pair()
        info[(0, 4)].update(item=0.16, orange=0.16)
        action, reason = strategy.choose(info, player=(2, 1), dash_stock=4)
        self.assertNotEqual(action[0], "dash")

    def test_target_in_the_dash_row_still_pays(self):
        info = self._pair()
        info[(2, 4)].update(item=0.16, orange=0.16)
        action, reason = strategy.choose(info, player=(2, 1), dash_stock=4)
        self.assertEqual(action[0], "dash")

    def test_a_full_stock_does_not_make_a_bare_pair_worth_it(self):
        # Having dashes to spare is not a reason to lose 280 shards with
        # one: the stock gate went out with the doctrine it served.
        action, reason = strategy.choose(self._pair(), player=(2, 1),
                                         dash_stock=20)
        self.assertNotEqual(action[0], "dash", reason)


class PerishableNeverScrolledAwayTests(unittest.TestCase):
    """Review 2026-08-22 ('conflicts' lens): when the tour cannot find
    a route inside its scroll budget, choose() falls through to
    explore - which scrolls right freely and kills the very perishable
    the budget was protecting. The budget is an invariant of the whole
    decision, not of one branch.

    Narrowed 2026-08-23 to perishables that can still be TAKEN. The
    original board walled the orange in with three pyramids and demanded
    the bot hold the world still for it anyway; with attacks disabled
    that orange was unreachable forever, and standing guard over it is
    the livelock that ended run 20260823T074036 (see
    PerishableVetoNeedsAWayThereTests). A prize behind a wall is already
    lost - the invariant protects the ones a route still reaches.
    """

    def test_an_unrouted_but_reachable_perishable_blocks_the_scroll(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        # Perishable at column 0 - one scroll kills it - with a free
        # column-0 lane still leading to it.
        info[(0, 0)].update(item=0.16, orange=0.16)
        info[(1, 1)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(2, 1),
                                         attacks_enabled=False)
        if action is not None and action[0] == "move":
            self.assertLess(tuple(action[1])[1], 2,
                            "no scrolling step while a col-0 pickup lives")


class DashEffectEvidenceTests(unittest.TestCase):
    """Review 2026-08-22 ('physics' lens): the dash-failure detector
    fires when the player cell is unchanged - which is true of EVERY
    successful dash, since the dash travels three cells right and the
    world scrolls the same three back. With two pyramids on the right
    before and after (routine: new ones scroll in), a working dash
    could disable dashing for the rest of the run. The inventory
    counter is direct evidence and is already read on that frame."""

    def test_spent_dash_is_never_called_ineffective(self):
        self.assertFalse(runner.dash_had_no_effect(
            {"dashes": 14}, {"dashes": 13},
            player_moved=False, obstacles_before=3, obstacles_after=3))

    def test_unspent_dash_with_unchanged_board_is_ineffective(self):
        self.assertTrue(runner.dash_had_no_effect(
            {"dashes": 14}, {"dashes": 14},
            player_moved=False, obstacles_before=3, obstacles_after=3))

    def test_unreadable_inventory_falls_back_to_the_board(self):
        self.assertTrue(runner.dash_had_no_effect(
            None, None, player_moved=False,
            obstacles_before=3, obstacles_after=3))
        self.assertFalse(runner.dash_had_no_effect(
            None, None, player_moved=False,
            obstacles_before=3, obstacles_after=0))


# ---------------------------------------------------------------------
# Retired 2026-08-22 with the six-mechanism suspicion stack they pinned
# (BurstZone, ClawMemory, ConfirmedItemMemory, DashConfettiSource,
# KnownWorld, LeftBandMemoryDecay, PendingReveal, RememberedSuspect,
# RightEdgeIngestion, ShiftAwareCarryover, ShiftGhost,
# StickySuspectFlicker, SuspectAppearance). Every behaviour they
# protected is now a property of the tracked world model and lives in
# tests/test_world_model.py: identity across the scroll and across
# cover (was: shift ghosts, sticky ages, decay misses), origin decided
# once at birth (was: appearances, carryover, burst holds, reveal
# whitelists), belief never re-litigated (was: remembered-suspect
# drops), and standing collects (was: memory pops and contradiction
# rules).
# ---------------------------------------------------------------------


class PyramidKillsClawTests(unittest.TestCase):
    """Replay harness n=107 (run 183056): a cell scored claw .15 AND
    pyramid .9 at once - the pyramid's glints trip the claw slash
    detector. Memory re-confirmed the 'claw' every frame, the tour
    targeted it, and the tap gate vetoed it every frame: four identical
    refused decisions. A cell cannot be both; the pyramid score
    (.88-.99, the strongest signal we have) wins."""

    def test_claw_on_a_pyramid_is_not_a_goal(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["claw"] = 0.15
        info[(2, 2)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertNotIn("claw", str(reason))
        if action is not None and action[0] == "move":
            self.assertNotEqual(tuple(action[1]), (2, 2))


class EarlyAdvanceTieBreakTests(unittest.TestCase):
    """User doctrine 2026-08-22 (correcting the short-lived scroll-late
    rule): between routes of equal taps and resources, the one that
    advances the world rightward EARLIER is the better one - advance is
    progress. The epsilon only breaks exact ties; a real cost gap
    (surcharges, items, budget) always dominates it."""

    def _grid(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(1, 3)].update(item=0.16, orange=0.16)
        info[(1, 1)]["pyramid"] = 0.9
        info[(0, 4)]["pyramid"] = 0.9
        info[(4, 2)]["pyramid"] = 0.9
        return info

    def test_equal_cost_routes_advance_early(self):
        step = strategy.shortest_action(self._grid(), (3, 1), {(1, 3)},
                                        prefer_direction="right")
        self.assertIsNotNone(step)
        target, obstacle, direction = step
        self.assertEqual(direction, "right")

    def test_genuinely_cheaper_scroll_first_still_wins(self):
        # The tie-break epsilon must never override a real cost gap:
        # same-row target straight ahead stays a plain right.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.16, orange=0.16)
        step = strategy.shortest_action(info, (2, 1), {(2, 3)},
                                        prefer_direction="right")
        target, obstacle, direction = step
        self.assertEqual(direction, "right")


class FrameClockTests(unittest.TestCase):
    """Review 2026-08-22 ('suspects' lens): every confetti/reveal
    window is expressed in `done`, which counts ACTIONS (done +=
    len(sent), up to 3 per frame), while the phenomena they bound are
    measured in FRAMES of animation. After a 3-tap batch the two-frame
    confetti window is already expired on the very next frame, so the
    protection evaporates precisely when the bot moves fastest. A
    frame clock ticks once per screenshot."""

    def test_frame_clock_ticks_once_per_screenshot(self):
        clock = runner.FrameClock()
        self.assertEqual(clock.now, 0)
        clock.tick()
        clock.tick()
        self.assertEqual(clock.now, 2)

    def test_batches_do_not_age_the_frame_clock(self):
        clock = runner.FrameClock()
        clock.tick()
        stamp = clock.now
        # Three taps sent in one batch, then the next screenshot.
        clock.tick()
        self.assertEqual(clock.now - stamp, 1,
                         "a batch must age the clock by one frame")


class FormingWallGateAgreementTests(unittest.TestCase):
    """Walk toward a forming wall only where the walk buys something.

    The rule exists to save a wall the next scroll would EAT: run
    20260822T234822 n=14 had (4,1),(4,2) in position plus (4,4) and the
    preview lit, and the explorer scrolled three times and expelled its
    own left side unbroken. That danger is real only while the run
    already touches column 1.

    A run that starts at column 2 is not in danger - the belt brings it
    closer for free - and walking to its launch cost seven paws in run
    20260828T211315 n=32-38 (user: "otra vez empezo a dar vueltas"): the
    rule walked the bot to the launch, the pair rule refused on arrival
    because a bare pair with a way around it is not worth 400 shards,
    explore walked it off, and the rule sent it back. The board never
    changed once, and the bot had been standing ON the launch when it
    started.

    That is also why the anticipation is confined here. This rule counts
    the pyramid the preview PROMISES; dash_path_pyramids counts only
    what has landed. Anywhere else that gap is a disagreement between
    the walk and the dash, which is what the loop was made of. Counting
    the promise on both sides is no fix either: a dash through a cell
    that is still empty breaks nothing.
    """

    def _forming(self):
        # Left side already at column 1, reinforcement promised.
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(4, 1)]["pyramid"] = 0.9
        info[(4, 2)]["pyramid"] = 0.9
        return info, [False, False, False, False, True]

    def test_it_walks_to_save_a_wall_the_scroll_would_eat(self):
        for stock in (1, 4, 20, None):
            info, preview = self._forming()
            action, reason = strategy.choose(info, player=(3, 1),
                                             preview=preview,
                                             dash_stock=stock)
            self.assertIn("forming wall", reason, f"stock={stock}")

    def test_a_run_starting_at_column_two_is_not_walked_to(self):
        # One column further right, so the belt cannot kill it: the same
        # board the user's loop was made of.
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(4, 2)]["pyramid"] = 0.9
        info[(4, 3)]["pyramid"] = 0.9
        _, reason = strategy.choose(info, player=(3, 1),
                                    preview=[False] * 4 + [True],
                                    dash_stock=38)
        self.assertNotIn("forming wall", reason)

    def test_three_run_positions_regardless_of_stock(self):
        # A 3-pyramid run always pays, so the bot must head for the
        # launch - by the veteran wall hunt or this rule, either label -
        # and must never scroll the run away instead.
        info, preview = self._forming()
        info[(4, 3)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(3, 1),
                                         preview=preview, dash_stock=1)
        self.assertIsNotNone(action)
        self.assertNotEqual(tuple(action[1]), (3, 2),
                            "scrolling right eats the forming wall")

    def test_the_user_board_stops_circling(self):
        # 20260828T211315 n=32-38, exactly as recorded. Nothing here may
        # send the bot walking to a launch - from any of the six cells
        # it circled.
        info = empty_grid()
        for cell in ((0, 0), (0, 1), (2, 2), (2, 3), (4, 0), (4, 4)):
            info[cell]["pyramid"] = 0.9
        preview = [False, False, True, False, False]
        for player in ((2, 1), (3, 1), (3, 0), (2, 0), (1, 1), (1, 0)):
            board = {cell: dict(values) for cell, values in info.items()}
            board[player]["player"] = 0.5
            _, reason = strategy.choose(board, player=player,
                                        preview=preview, dash_stock=38)
            self.assertNotIn("forming wall", reason, f"desde {player}")


class ScreenColumnScrollTests(unittest.TestCase):
    """Review 2026-08-22 ('physics' lens): shortest_action prices a
    right step as scrolling by its FRAME column (nxt[1] >= 2), but the
    world only scrolls when the tap enters SCREEN column >= 2, and
    screen col = frame col - scrolls already taken. A route that
    scrolls once, detours left around a pyramid and steps right again
    into frame col 2 (screen col 1 - free by the code's own doctrine)
    is charged a phantom second scroll.

    Adjudication (measured, not assumed): the mispricing can only fire
    on a right step taken AFTER a left step that followed a scroll,
    and on a 5x5 Manhattan grid that zigzag is never on an optimal
    route - the router always holds a same-cost zigzag-free twin. The
    fix (charge by screen column) is therefore physics-correctness
    with no reachable routing change, and these tests pin that the
    documented budget behaviours did not move."""

    def test_scroll_accounting_matches_real_taps(self):
        # Each right tap into screen column 2 scrolls once: reaching
        # frame col 3 costs exactly two scrolls, no more.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 3)].update(item=0.16, orange=0.16)
        self.assertIsNotNone(
            strategy.shortest_action(info, (2, 1), {(2, 3)},
                                     protect=[(0, 2)]))

    def test_col_zero_target_still_forbids_every_scroll(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(0, 0)].update(item=0.16, orange=0.16)
        info[(4, 2)].update(item=0.16, orange=0.16)
        step = strategy.shortest_action(info, (2, 1), {(4, 2)},
                                        protect=[(0, 0)])
        self.assertIsNone(step, "a col-0 stop tolerates no scroll")

    def test_col_zero_to_col_one_right_is_still_free(self):
        info = empty_grid()
        info[(2, 0)]["player"] = 0.2
        info[(2, 1)].update(item=0.16, orange=0.16)
        step = strategy.shortest_action(info, (2, 0), {(2, 1)},
                                        protect=[(4, 0)])
        self.assertIsNotNone(step, "col0->col1 scrolls nothing")


class CorridorDashRowTests(unittest.TestCase):
    """Review 2026-08-22 ('conflicts' lens, confirmed): the corridor
    override gathers its evidence from the ATTACK TARGET's row but
    fires ('dash', player) along the PLAYER's row - vertical attacks
    make those different rows, so it can spend 400 shards dashing an
    empty lane. It is also the only dash rule that never sees
    left_band_risk, so it deletes real remembered pickups the
    strategy-side rules would have protected."""

    def _preview(self, row):
        return [i == row for i in range(5)]

    def test_vertical_attack_never_triggers_the_corridor_dash(self):
        action = ("attack", (2, 1), "up")
        self.assertFalse(runner.corridor_dash_due(
            action, (2, 84), 86, self._preview(2), True, player=(3, 1)))

    def test_own_row_corridor_still_fires(self):
        action = ("attack", (3, 2), "right")
        self.assertTrue(runner.corridor_dash_due(
            action, (3, 84), 86, self._preview(3), True, player=(3, 1)))

    def test_left_band_pickup_defers_the_corridor_dash(self):
        action = ("attack", (3, 2), "right")
        self.assertFalse(runner.corridor_dash_due(
            action, (3, 84), 86, self._preview(3), True, player=(3, 1),
            left_band_risk=True))


class IncomingWallAlignmentTests(unittest.TestCase):
    """User directive 2026-08-22: the sixth-column preview exists
    precisely to anticipate walls - when a wall is coming, position for
    the dash instead of exploring elsewhere (run 20260822T215547
    n=49-53: the wall entered row 3 while the bot scrolled from row 4,
    then paid 2 taps to walk to the launch). Signal = pyramid visible
    at (r,4) AND preview[r] lit: two independent confirmations of a
    run entering row r. The explorer aligns to that row FIRST -
    vertical steps do not scroll, so the wall stands still - and then
    scrolls from there, forming the launch under its own feet."""

    def test_explorer_aligns_to_the_incoming_wall_row(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(3, 4)]["pyramid"] = 0.9
        preview = [False, False, False, True, False]
        action, reason = strategy.choose(info, player=(4, 1),
                                         preview=preview)
        self.assertEqual(action[0], "move")
        self.assertEqual(tuple(action[1]), (3, 1))

    def test_no_preview_confirmation_keeps_normal_explore(self):
        # A lone edge pyramid without the preview lit is not a wall
        # signal: plain explore-right stands.
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(3, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(4, 1),
                                         preview=None)
        self.assertEqual(action, ("move", (4, 2), "right"))

    def test_already_aligned_scrolls_a_fully_outside_wall_in(self):
        # Standing on the incoming row with the wall entirely outside
        # (edge + preview only): keep scrolling right - every scroll
        # pulls the wall (and the launch) toward the bot.
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(3, 4)]["pyramid"] = 0.9
        preview = [False, False, False, True, False]
        action, reason = strategy.choose(info, player=(3, 1),
                                         preview=preview)
        self.assertEqual(action, ("move", (3, 2), "right"))

    def test_partial_wall_already_in_place_is_not_scrolled_away(self):
        # Run 20260822T234822 n=14: row 4 held (4,1),(4,2) IN POSITION
        # plus (4,4) and the preview lit - a 5-pyramid wall forming
        # with its left side already at the launch. The explorer
        # scrolled 3 times and expelled its own (4,1),(4,2) off the
        # board unbroken. Physics: every scroll eats the left side of
        # a forming wall. With a partial run in columns <=2 and
        # reinforcements incoming on the same row, scrolling that row
        # is forbidden - hold position and let the wall connect.
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        info[(4, 1)]["pyramid"] = 0.9
        info[(4, 2)]["pyramid"] = 0.9
        info[(4, 4)]["pyramid"] = 0.9
        preview = [False, False, False, False, True]
        action, reason = strategy.choose(info, player=(3, 1),
                                         preview=preview)
        if action is not None:
            self.assertNotEqual(action, ("move", (3, 2), "right"))
            self.assertNotEqual(tuple(action[1])[1], 2,
                                "no scrolling right while the wall forms")


class ExplorerNeverBuysGarraOverFreeStepTests(unittest.TestCase):
    """Run 20260822T215547 n=47: boxed left and right by pyramids at
    (4,0)/(4,2) with a FREE step up at (3,1), the explorer spent a
    200-shard garra on (4,2) - the anti-reverse hysteresis (-30) sank
    the free move below the attack's score because the bot had just
    walked down. A garra never outbids a free step while exploring:
    attacks only when EVERY candidate is an obstacle."""

    def test_free_reverse_step_beats_the_attack(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(4, 0)]["pyramid"] = 0.9
        info[(4, 2)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, previous_direction="down",
                                         player=(4, 1))
        self.assertEqual(action[0], "move")
        self.assertEqual(tuple(action[1]), (3, 1))

    def test_truly_boxed_explorer_still_attacks(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        for cell in ((4, 0), (4, 2), (3, 1)):
            info[cell]["pyramid"] = 0.9
        action, reason = strategy.choose(info, previous_direction="down",
                                         player=(4, 1))
        self.assertEqual(action[0], "attack")


class SlidingWaitCapTests(unittest.TestCase):
    """Run 20260822T212332 n=82: the mid-slide WAIT had no retry cap
    and never refreshed its reference strip, so a board whose content
    settled at a fractional alignment against the FROZEN prev_strip
    read as 'sliding' forever - 47 consecutive waits until the user
    killed the run. Every other WAIT in the loop is capped; this one
    waits at most 3 frames, then the runner rebases prev_strip on the
    current frame and moves on (one lost measurement, not a deadlock)."""

    def test_waits_below_the_cap(self):
        self.assertTrue(runner.should_wait_for_slide(True, 0))
        self.assertTrue(runner.should_wait_for_slide(True, 2))

    def test_cap_exhausted_stops_waiting(self):
        self.assertFalse(runner.should_wait_for_slide(True, 3))
        self.assertFalse(runner.should_wait_for_slide(True, 7))

    def test_not_sliding_never_waits(self):
        self.assertFalse(runner.should_wait_for_slide(False, 0))


class SuspectsAreTargetsNotTerrainTests(unittest.TestCase):
    """Run 20260823T033159 n=20-23 (user: 'dio un paso adelante y
    después se devolvió'): post-pickup confetti at (1,1) and (2,1) made
    the free column-1 descent illegal, so the bot scrolled three times
    to bring the dash orb closer instead - and those scrolls carried
    the pyramid at (2,4) into (2,1), blocking that lane FOR REAL. Eight
    taps where six sufficed, and the obstacle was its own doing.

    The confusion came from the retired suspicion stack: a suspect is a
    cell that may hold NOTHING, which is a reason not to walk there FOR
    IT - not a reason to treat empty ground as a wall. Pyramids are the
    only impassable thing on this board. Making suspicion a property of
    goals instead of terrain also retires three waiting rules built to
    escape the walls it invented."""

    def test_the_planner_descends_through_confetti(self):
        # The exact board of run 20260823T033159 n=20: the orb is three
        # rows down in column 1 and the lane holds confetti. The bot
        # must walk down it, not scroll around it.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(3, 1)].update(item=0.16, orange=0.16)
        for cell in ((1, 1), (2, 1)):
            info[cell].update(item=0.16, orange=0.16)
        action, reason = strategy.choose(
            info, player=(0, 1), ignored_targets={(1, 1), (2, 1)},
            suspect_cells={(1, 1), (2, 1)})
        self.assertEqual(action[0], "move")
        self.assertEqual(action[2], "down", "confetti is ground, not a wall")

    def test_a_suspect_is_still_not_a_goal(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)].update(item=0.16, orange=0.16)
        action, reason = strategy.choose(info, player=(2, 1),
                                         ignored_targets={(2, 2)},
                                         suspect_cells={(2, 2)})
        self.assertNotIn("orange targets", reason)

    def test_the_tap_gate_allows_stepping_on_a_suspect(self):
        info = empty_grid()
        info[(2, 2)].update(item=0.16, orange=0.16)
        self.assertFalse(runner.unsafe_move_tap(info, (2, 2),
                                                suspects={(2, 2)}))

    def test_the_tap_gate_still_refuses_a_pyramid(self):
        info = empty_grid()
        info[(2, 2)]["pyramid"] = 0.9
        self.assertTrue(runner.unsafe_move_tap(info, (2, 2)))


class FragileDetourTests(unittest.TestCase):
    """Run 20260822T142042 n=194 (user: 'podía continuar su camino'):
    the route to the perishable orange at (4,1) banned EVERY right step,
    including the col0-to-col1 right that does not scroll - the free
    4-step detour around the pyramid became illegal and the only lawful
    route was a 200-shard garra through (3,1). Only rights into column
    2+ scroll the world; a right into column 1 erodes nothing."""

    def test_free_detour_beats_the_garra_for_a_perishable(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, orange=0.10)
        info[(3, 1)]["pyramid"] = 0.9
        info[(3, 3)]["pyramid"] = 0.9
        info[(2, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info)
        self.assertNotEqual(action[0], "attack")

    def test_scrolling_rights_stay_banned_for_fragile_targets(self):
        step = strategy.shortest_action(
            {**{(r, c): {"player": 0.0, "item": 0.0, "pyramid": 0.0,
                         "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "highlight": 1.0}
                for r in range(5) for c in range(5)}},
            (2, 1), {(2, 0)})
        # Target at col 0: route is a single left step; a right can
        # never appear (this pins the ban's purpose, not its letter).
        target, obstacle, direction = step
        self.assertEqual(direction, "left")


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


# (SilentRejectionTests retired 2026-08-23 with silent_rejection itself.
# It caught refusals by POSITION - a confidently seen player still on
# the pre-move cell - and one of its own tests,
# test_scroll_rides_cannot_be_judged, pinned the blind spot: riding right
# leaves the player on the same screen cell by design, so the most common
# move in the game could never be judged at all. The paw receipt judges
# every move the same way, and tests/test_step_ledger.py RefusedTapTests
# carries the replacement law, scroll rides included.)


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
    confirmed). The ladder of attempts now belongs to the overlay
    arbiter (see tests/test_overlays.py and test_overlay_arbiter.py);
    what stays here is the geometry of the dismiss point itself."""

    def test_dismiss_point_sits_outside_centered_dialogs(self):
        x, y = runner.DISMISS_TAP_XY
        self.assertLess(x, 60)          # left of any dialog frame
        self.assertTrue(300 <= y <= 900)  # away from HUD top and bottom bars


class UnstableWallHoldTests(unittest.TestCase):
    """Run 20260822T153206 n=97-101 (user: 'indecisión para hacer un
    dash sobre 3 pirámides'): frame one sights the 3-wall but stability
    needs a second frame, so the tour acted (a step DOWN toward an orb)
    and frame two's stabilized hunt walked it right back - three wasted
    steps. When a fresh wall is in sight and not yet stable, a plain
    move waits one frame instead of acting on the frame of doubt. Free
    grabs and perishable rescues still go; two holds max so a
    flickering wall cannot stall the bot."""

    def test_plain_move_holds_while_the_wall_stabilizes(self):
        self.assertTrue(runner.should_hold_for_wall(
            (2, 0), False, ("move", (4, 1), "down"),
            "dash_orb targets=[(3, 4)]", holds=0))

    def test_stable_wall_never_holds(self):
        self.assertFalse(runner.should_hold_for_wall(
            (2, 0), True, ("move", (4, 1), "down"),
            "dash_orb targets=[(3, 4)]", holds=0))

    def test_no_wall_never_holds(self):
        self.assertFalse(runner.should_hold_for_wall(
            None, False, ("move", (4, 1), "down"),
            "dash_orb targets=[(3, 4)]", holds=0))

    def test_free_grab_and_rescue_still_go(self):
        self.assertFalse(runner.should_hold_for_wall(
            (2, 0), False, ("move", (2, 2), "right"),
            "adjacent item=(2, 2)", holds=0))
        self.assertFalse(runner.should_hold_for_wall(
            (2, 0), False, ("move", (3, 0), "left"),
            "orange perishable targets=[(3, 0)]", holds=0))

    def test_two_holds_break_the_stall(self):
        self.assertFalse(runner.should_hold_for_wall(
            (2, 0), False, ("move", (4, 1), "down"),
            "dash_orb targets=[(3, 4)]", holds=2))

    def test_non_move_actions_never_hold(self):
        self.assertFalse(runner.should_hold_for_wall(
            (2, 0), False, ("dash", (2, 1), "right"),
            "dash pair: 2 pyramids in path", holds=0))


class CommittedWallDashRiskTests(unittest.TestCase):
    """Run 20260822T162851 n=52: the committed wall dash fired while a
    remembered orange sat at (0,1) - its 3-column scroll pushed the
    orange off the board (user: 'dash no recogiendo una energía
    arriba'). The strategy-side wall rule defers to left-band pickups;
    the runner override now does too."""

    def test_left_band_pickup_defers_the_committed_dash(self):
        self.assertFalse(runner.committed_wall_dash(
            ((4, 1), 50, 10), (4, 1), 51, last_dash=None,
            suspect_cells=(), scrolls_now=10, left_band_risk=True))

    def test_clear_left_band_keeps_the_committed_dash(self):
        self.assertTrue(runner.committed_wall_dash(
            ((4, 1), 50, 10), (4, 1), 51, last_dash=None,
            suspect_cells=(), scrolls_now=10, left_band_risk=False))


class AdjacentSuspectHoldTests(unittest.TestCase):
    """Run 20260822T162851 n=49-50: the steps card at (4,2) was
    suspect, so the tour left it out and stepped UP toward a far
    orange; the card confirmed on the very next frame and the tour
    walked right back down. A suspect ONE step away decides the plan
    either way - one 0.4s hold replaces the two-step vaiven.

    RETIRED 2026-08-22 (user: 'ya sabemos que genera confeti,
    deberíamos simplemente ignorarlo, se queda trabado ahí'): under
    the known-world doctrine a left-band suspect can never be believed
    or targeted, so there is nothing to wait FOR - and an adjacent
    suspect is ALWAYS left-band because the digi lives in columns 0-1.
    The n=49-50 vaiven this hold fixed is covered by the sticky TTL
    now (the card is ignored for a few frames and the plan holds its
    course). Run 20260822T174628: 22 of 58 frames were WAITs."""

    def test_adjacent_suspect_hold_is_retired(self):
        self.assertFalse(hasattr(runner, "should_hold_for_adjacent_suspect"))

    def test_left_band_only_suspects_never_hold_the_frame(self):
        # All goals suspect but every suspect is known-world confetti:
        # nothing to adjudicate, keep moving.
        self.assertFalse(runner.should_hold_for_suspects(
            "explore right", [(2, 1)], {(2, 1), (1, 0)}, holds=0))

    def test_right_band_suspects_still_hold(self):
        self.assertTrue(runner.should_hold_for_suspects(
            "explore right", [(2, 3)], {(2, 3)}, holds=0))


class ClawCellVisibilityTests(unittest.TestCase):
    """Run 20260822T162851 n=176-181: a claw ghost (batch tap swallowed,
    memory over-shifted) walked the bot to an empty cell, and neither
    the suspect system nor the scroll reconciler could see it - both
    built their cell sets from item>.06, which claws fail by design
    (claw mask >.10 with item low). Claw cells join the set."""

    def test_claw_cells_count_as_item_cells(self):
        info = empty_grid()
        info[(3, 2)]["claw"] = 0.15
        info[(1, 1)].update(item=0.10, orange=0.10)
        self.assertEqual(runner.item_cells_of(info), frozenset({(3, 2), (1, 1)}))


class ColumnZeroDoctrineTests(unittest.TestCase):
    """User doctrine 2026-08-22 (PNG debug_0148): rescues and panic
    belong to column 0 ONLY. A column-1 pickup survives one scroll -
    it is a normal target, not an emergency. The old col<=1 fragility
    banned scrolling rights and forced 'weird' left-edge routes."""

    def test_column_one_target_is_not_labeled_perishable(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 1)].update(item=0.10, orange=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertFalse(reason.startswith("orange perishable"))

    def test_column_zero_target_keeps_the_perishable_label(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(4, 0)].update(item=0.10, orange=0.10)
        info[(0, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info)
        self.assertTrue(reason.startswith("orange perishable"))

    def test_column_one_route_may_spend_its_one_scroll(self):
        # A column-1 target survives exactly one scroll, so a route
        # with ONE scrolling right is legal (the old col<=1 ban forced
        # a garra or a left-edge crawl); a col-0 target still allows
        # none, and multi-scroll right-arounds stay banned.
        info = empty_grid()
        info[(2, 0)]["pyramid"] = 0.9
        info[(2, 1)]["pyramid"] = 0.9
        info[(3, 1)].update(item=0.10, orange=0.10)
        step = strategy.shortest_action(info, (1, 1), {(3, 1)},
                                        allow_obstacles=True)
        self.assertIsNotNone(step)
        target, obstacle, direction = step
        self.assertEqual(direction, "right")

    def test_protected_column_zero_twin_bans_the_scroll(self):
        # The leg to (4,1) alone may spend one scroll, but with the
        # plan's next stop at column 0 the same scroll would kill it:
        # the protect list carries the whole plan's fragility.
        info = empty_grid()
        info[(3, 0)]["pyramid"] = 0.9
        info[(3, 1)]["pyramid"] = 0.9
        info[(4, 1)].update(item=0.10, orange=0.10)
        info[(4, 0)].update(item=0.10, orange=0.10)
        step = strategy.shortest_action(info, (2, 1), {(4, 1)},
                                        allow_obstacles=False,
                                        protect=[(4, 0)])
        self.assertIsNone(step)


# (ScrollUndoTests retired 2026-08-23 with shift_items_right. An
# over-counted scroll only existed because memory was shifted
# OPTIMISTICALLY at tap time and then argued with the pixel sensor a
# frame later. Memory now shifts once, from the paw receipt, and never
# has to walk backwards - tests/test_step_ledger.py ConveyorLawTests
# pins the single forward law that replaced it.)


class ExplorerNeverStepsBackTests(unittest.TestCase):
    """Run 20260822T183056 n=14: with up and right suspect-blocked the
    explorer stepped plain LEFT - a free move backward that buys
    nothing (the user's vaiven). Same law as the left attack: while
    suspects block the alternatives, waiting a frame beats walking
    backward. A genuinely cornered explorer (real pyramids, no
    suspects) may still escape left."""

    def test_explorer_never_attacks_while_suspects_block(self):
        # Run 20260822T184638 n=41 (user: 'garra hacia arriba en vez
        # de un dash claro'): surrounded by post-pickup suspects, the
        # explorer attacked the pyramid ABOVE - the left-only law was
        # too narrow. While suspects block alternatives, no explore
        # attack in ANY direction: wait the frame instead.
        info = empty_grid()
        info[(1, 1)]["player"] = 0.2
        info[(0, 1)]["pyramid"] = 0.9
        info[(1, 2)].update(item=0.10, orange=0.10)
        info[(2, 1)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(
            info, ignored_targets={(1, 2), (2, 1)},
            suspect_cells={(1, 2), (2, 1)})
        if action is not None:
            self.assertNotEqual(action[0], "attack")

    def test_left_step_yields_to_waiting_while_suspects_block(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(3, 1)].update(item=0.10, pink=0.10)
        info[(4, 2)].update(item=0.10, pink=0.10)
        action, reason = strategy.choose(
            info, ignored_targets={(3, 1), (4, 2)},
            suspect_cells={(3, 1), (4, 2)})
        if action is not None:
            self.assertFalse(action[0] == "move" and action[2] == "left")

    def test_cornered_without_suspects_still_escapes_left(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(3, 1)]["pyramid"] = 0.9
        info[(4, 2)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, attacks_enabled=False)
        self.assertEqual(action, ("move", (4, 0), "left"))


class BarePairNeverFiresTests(unittest.TestCase):
    """A bare pair is not break-even. It is a 280-shard loss.

    This class replaces DashStockGateTests, which gated the bare pair on
    dash stock because "two REAL pyramids pay for the dash on their own -
    each break drops at ~46% and the dash collects its drops in the same
    motion". The runner's own dash_result records refute the second half
    (n=556 dashes):

        2 pyramids, no item in the path   n=427   +12.9 energy
        3 pyramids, no item in the path   n= 92   +20.7
        2 pyramids, an item in the path   n= 33  +108.5

    The median of a bare dash is 20 - the passive tick, which arrives
    whether or not anything is dashed. So the dash collects what is
    ALREADY in its path and not what its breaks drop; two breaks at the
    measured 44% should have shown ~110 and show the clock instead.

    Priced out: 400 shards buys three columns of advance, worth three
    steps (120) on foot, and going around two pyramids is two paws (80).
    427 of 556 recorded dashes were this bare pair: 170,800 shards.
    """

    def bare_pair(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.9
        info[(2, 3)]["pyramid"] = 0.9
        return info

    def test_a_walled_pair_fires_because_the_detour_is_not_there(self):
        """The veto quotes a detour; it has to exist to be quoted.

        Run 20260828T185642 n=11 (user stopped the run over it): pyramids
        above, below and ahead. The sidestep the veto prices at two paws
        was not on the board, so the real alternatives were two garras -
        400 shards and no advance - or a walk back through column 0. The
        dash breaks both AND advances three columns. The explorer, with
        the dash vetoed, fell through to the forward garra: half the
        price for a quarter of the result.

        Of 266 bare pairs in the recordings, 227 (85%) do have the
        sidestep and stay vetoed; 39 (15%) look like this.
        """
        info = self.bare_pair()
        for cell in ((1, 1), (3, 1)):
            info[cell]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(2, 1))
        self.assertEqual(action[0], "dash", reason)

    def test_one_open_side_is_enough_to_keep_the_veto(self):
        # Only the row below is walled: stepping up and forward is still
        # two paws, so the pair stays refused.
        info = self.bare_pair()
        info[(3, 1)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(2, 1))
        self.assertNotEqual(action[0], "dash", reason)

    def test_a_side_that_is_free_but_walled_ahead_is_no_detour(self):
        # (1,1) is free, but (1,2) is a pyramid: stepping aside buys
        # nothing, so it does not count as a way around.
        info = self.bare_pair()
        info[(3, 1)]["pyramid"] = 0.9
        info[(1, 2)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, player=(2, 1))
        self.assertEqual(action[0], "dash", reason)

    def test_a_bare_pair_never_fires_however_full_the_stock(self):
        for stock in (None, 5, 30, 99):
            action, reason = strategy.choose(self.bare_pair(),
                                             dash_stock=stock)
            self.assertNotEqual(action[0], "dash", f"stock={stock}: {reason}")

    def test_an_item_in_the_path_still_pays(self):
        # The 108.5 row: the dash collects what is already lying there.
        info = self.bare_pair()
        info[(2, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, dash_stock=5)
        self.assertEqual(action[0], "dash", reason)

    def test_a_wall_of_three_still_fires(self):
        info = self.bare_pair()
        info[(2, 4)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dash_stock=5)
        self.assertEqual(action[0], "dash", reason)

    def test_the_paw_that_lines_up_a_bare_pair_is_not_spent_either(self):
        # The launch approach used the same stock gate. Walking a paw to
        # reach a dash that loses 280 shards loses the paw as well.
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(3, 2)]["pyramid"] = 0.9
        info[(3, 3)]["pyramid"] = 0.9
        action, reason = strategy.choose(info, dash_stock=30)
        self.assertNotIn("pair launch", reason)


class ExplorerNeverAttacksLeftTests(unittest.TestCase):
    """Run 20260822T160202 n=72: up and right were suspect-blocked
    (confetti), so the explorer's only 'preferred' candidate was the
    pyramid on its LEFT - 200 shards to explore backwards. The world
    itself moves left: a left pyramid never needs breaking. Waiting a
    frame for the suspects to adjudicate is always cheaper."""

    def test_left_pyramid_is_never_an_explore_attack(self):
        info = empty_grid()
        info[(4, 1)]["player"] = 0.2
        info[(4, 0)]["pyramid"] = 0.9
        info[(3, 1)].update(item=0.10, orange=0.10)
        info[(4, 2)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(
            info, ignored_targets={(3, 1), (4, 2)},
            suspect_cells={(3, 1), (4, 2)})
        if action is not None:
            self.assertNotEqual(
                (action[0], action[2] if len(action) > 2 else None),
                ("attack", "left"))
            self.assertFalse(action[0] == "attack"
                             and action[1] == (4, 0))


class PixelScrollTests(unittest.TestCase):
    """Doctrine 2026-08-22 (user): reconcile the world by MEASURING it,
    not by counting taps. Run 20260822T164337 n=30-32: a tap swallowed
    by latency left memory one column ahead, the re-tap landed on the
    pyramid scrolling in, and the HUD counter shows two hidden garras
    (41->39) before a dash crossed the same row. The board strip of
    consecutive settled frames is cross-correlated at shifts 0..3
    columns; the argmin IS the scroll, whatever the taps claimed."""

    # The strip covers the board's RIGHT 3 COLUMNS only: the player
    # sprite (columns 0-1, big, static) anchored a full-board
    # alignment at zero and real scrolls measured 0 (run
    # 20260822T172446 n=73-76: full-board 0.0, right-3-cols 1.04).
    # Three columns of strip can verify shifts up to 2; a dash's 3 is
    # out of range and trusts the tap count.

    @staticmethod
    def strip_with_block(col, width=90, height=30, cols=3):
        import numpy as np
        z = np.zeros((height, width), dtype=float)
        cw = width // cols
        z[5:25, col * cw + 3:col * cw + cw - 3] = 200.0
        return z

    def test_static_board_measures_zero(self):
        a = self.strip_with_block(2)
        self.assertEqual(runner.measure_scroll_columns(a, a), 0)

    def test_one_column_shift_is_measured(self):
        prev = self.strip_with_block(2)
        cur = self.strip_with_block(1)
        self.assertEqual(runner.measure_scroll_columns(prev, cur), 1)

    def test_two_column_shift_is_measured(self):
        prev = self.strip_with_block(2)
        cur = self.strip_with_block(0)
        self.assertEqual(runner.measure_scroll_columns(prev, cur,
                                                       max_cols=2), 2)

    def test_confetti_noise_does_not_fool_the_measurement(self):
        import numpy as np
        prev = self.strip_with_block(2)
        cur = self.strip_with_block(1)
        cur[8:16, 4:14] = 180.0   # confetti patch away from the block
        self.assertEqual(runner.measure_scroll_columns(prev, cur), 1)


# (RejectionGraceTests retired 2026-08-23 with rejection_needs_grace.
# The late-landing tap it defended against - run 20260822T175424 n=2-5,
# a "refused" move the next frame showed had landed - cannot fool the
# receipt: a late tap still gets charged, and the charge is what the
# runner reads. The "same cell refused twice mints the wall" rule that
# replaced it costs no frame at all, because the first refusal is
# replanned from a state the ledger proves did not change.)


class SlidingBoardTests(unittest.TestCase):
    """Run 20260822T171206: seventeen claimed>measured reconciliations
    (five consecutive at n=91-95) because the scroll lands AFTER the
    screenshot - the sensor read 0, memory was unshifted, and when the
    scroll arrived late the board and memory were desynced: cannot-move
    toasts, phantom obstacles, and a garra spent on an empty cell
    (n=163). Two defenses: pixel-granular measurement detects a board
    caught MID-slide (best alignment far from a whole column), and a
    measured shortfall waits one extra frame for the late scroll before
    reconciling."""

    @staticmethod
    def strip_with_block(px_off, width=135, height=30):
        import numpy as np
        z = np.zeros((height, width), dtype=float)
        z[5:25, 60 - px_off:100 - px_off] = 200.0
        return z

    def test_whole_column_shift_is_settled(self):
        prev = self.strip_with_block(0)
        cur = self.strip_with_block(45)   # exactly one column (135/3)
        cols, sliding = runner.measure_scroll_px(prev, cur)
        self.assertEqual(cols, 1)
        self.assertFalse(sliding)

    def test_half_column_shift_is_sliding(self):
        prev = self.strip_with_block(0)
        cur = self.strip_with_block(22)   # mid-animation
        cols, sliding = runner.measure_scroll_px(prev, cur)
        self.assertTrue(sliding)

    def test_static_board_is_settled_zero(self):
        prev = self.strip_with_block(0)
        cols, sliding = runner.measure_scroll_px(prev, prev)
        self.assertEqual((cols, sliding), (0, False))

    # (test_shortfall_waits_once_then_reconciles retired 2026-08-23 with
    # scroll_shortfall_wait. The wait existed because the pixel sensor
    # could not tell a LATE scroll from a SWALLOWED tap and bought a
    # frame of silence to find out - 14 of the 186 frames of run
    # 20260823T074036. The paw receipt answers outright, and neither
    # answer is improved by waiting. The mid-slide detection this class
    # also covers is untouched and still tested above.)


class PointlessGarraTests(unittest.TestCase):
    """Run 20260822T171206 n=163: a cannot-move toast minted a phantom
    obstacle at (1,1), and one decision later the router ATTACKED it -
    200 shards swung at an empty cell, then an 8-step detour around a
    wall that did not exist. A garra only ever goes to a cell the
    DETECTION shows as a pyramid; a phantom that vision cannot confirm
    is dropped instead of attacked."""

    def test_attack_on_visually_empty_cell_is_pointless(self):
        info = empty_grid()
        self.assertTrue(runner.pointless_attack(info, (1, 1)))

    def test_attack_on_a_real_pyramid_is_fine(self):
        info = empty_grid()
        info[(1, 1)]["pyramid"] = 0.9
        self.assertFalse(runner.pointless_attack(info, (1, 1)))


class ActionDelayTests(unittest.TestCase):
    """User directive 2026-08-22: timings live INSIDE the bot, not in a
    CLI flag - fast where nothing animates, slower where the game runs
    an animation that swallows taps (run 20260822T165752 n=6-12: six
    rapid rights during lag, measured scroll 0 - a whole batch eaten).
    Plain steps are the floor (~0.35s), scrolls and pickups wait for
    their animation, garra and dash wait the longest, and the jitter
    is a fraction of the base so pacing stays human."""

    def test_plain_move_is_the_floor(self):
        d = runner.action_delay("move", rand=lambda: 0.0)
        self.assertAlmostEqual(d, runner.ACTION_DELAYS["move"])
        self.assertGreaterEqual(d, 0.3)

    def test_animations_wait_longer(self):
        base = lambda k, **kw: runner.action_delay(k, rand=lambda: 0.0, **kw)
        self.assertGreater(base("move", scrolled=True), base("move"))
        self.assertGreater(base("move", picked_up=True),
                           base("move", scrolled=True) - 0.2)
        self.assertGreater(base("attack"), base("move", scrolled=True))
        self.assertGreater(base("dash"), base("attack"))

    def test_jitter_is_bounded_fraction_of_base(self):
        lo = runner.action_delay("move", rand=lambda: 0.0)
        hi = runner.action_delay("move", rand=lambda: 1.0)
        self.assertGreater(hi, lo)
        self.assertLessEqual(hi, lo * (1 + runner.JITTER_FRACTION) + 1e-9)


class LagGuardTests(unittest.TestCase):
    """After the pixel sensor reports lost taps (claimed > measured),
    the game is lagging: batching more taps into the freeze only feeds
    it. Batches drop to single steps for the next two decisions."""

    def test_cooldown_forces_single_steps(self):
        self.assertEqual(runner.lag_batch_limit(2, 3), 1)
        self.assertEqual(runner.lag_batch_limit(1, 3), 1)

    def test_no_cooldown_keeps_the_batch(self):
        self.assertEqual(runner.lag_batch_limit(0, 3), 3)


class DashScrollCountTests(unittest.TestCase):
    """Run 20260822T153206 n=123-126, user PNG debug_0124: the world
    scrolls only what it takes to clamp the digi back to column 1 -
    three columns when the dash launches from column 1, but only TWO
    from column 0. The hardcoded 3 shifted memory one column too far
    on col-0 launches: the remembered orange (3,3) became a ghost at
    the empty cell (3,0) while the real one surfaced at (3,1) as a
    fresh suspect. The bot grabbed the real one, then walked left to
    collect the ghost. Same signature at n=101-103 with the dash orb."""

    def test_dash_from_column_one_scrolls_three(self):
        self.assertEqual(runner.dash_scroll_count(1), 3)

    def test_dash_from_column_zero_scrolls_two(self):
        self.assertEqual(runner.dash_scroll_count(0), 2)


class HiddenGarraTests(unittest.TestCase):
    """HUD counter audit, run 20260822T142042: the attack counter
    dropped ~7 more times than the log sent attacks. A 'move' tap onto
    a cell the game shows as a pyramid EXECUTES a garra - the user
    watched them (debug 21, 26, 153, 499) while the events log said
    'move'. Two doors, both closed here: memory painting an item over
    a cell that is now a pyramid, and the tap itself going out without
    checking what the cell holds."""

    def test_memory_never_paints_over_a_visible_pyramid(self):
        info = empty_grid()
        info[(1, 0)]["pyramid"] = 0.9
        merged = runner.merge_remembered_items(
            info, {(1, 0): ("orange", 4)}, (2, 2))
        self.assertLessEqual(merged[(1, 0)]["item"], .06)

    def test_claw_memory_never_paints_over_a_visible_pyramid(self):
        info = empty_grid()
        info[(1, 0)]["pyramid"] = 0.9
        merged = runner.merge_remembered_items(
            info, {(1, 0): ("claw", 4)}, (2, 2))
        self.assertLessEqual(merged[(1, 0)].get("claw", 0.0), .10)

    def test_move_tap_onto_a_pyramid_is_unsafe(self):
        info = empty_grid()
        info[(1, 0)]["pyramid"] = 0.9
        self.assertTrue(runner.unsafe_move_tap(info, (1, 0)))
        self.assertFalse(runner.unsafe_move_tap(info, (1, 1)))

    def test_a_pyramid_under_confetti_still_refuses_the_tap(self):
        # The precise replacement for the retired suspect veto (run
        # 20260822T160202 n=89, one hidden 200-shard garra): the world
        # model keeps the pyramid's own track when a card is painted
        # over it, the runner merges it back as an obstacle, and the
        # gate refuses it as the pyramid it is - without turning every
        # confetti cell into a wall.
        world = world_model.WorldModel()
        world.observe({"items": {}, "pyramids": {(1, 1)}}, shift=0)
        world.observe({"items": {(1, 1): "orange"}, "pyramids": set()},
                      shift=0)
        self.assertIn((1, 1), world.believed_pyramids())
        info = empty_grid()
        info[(1, 1)].update(item=0.16, orange=0.16)
        merged = runner.merge_phantom_obstacles(
            info, {cell: 9 for cell in world.believed_pyramids()}, 0)
        self.assertTrue(runner.unsafe_move_tap(merged, (1, 1)))


class PocketRowsAreNotProgressTests(unittest.TestCase):
    """A row blocked at the scroll column cannot be advanced from.

    Run 20260822T184638 n=66-67, replayed through today's planner: boxed
    into rows 3 and 4 (both walled at column 2, rows 0-2 sealed off), the
    explorer stepped DOWN into row 4 - whose only exit is back up - and
    the next frame stepped back. Two paws, no progress, still boxed. The
    curiosity bonus had actively lured it in: it counts pyramids to the
    right as a dash opportunity, and the lone (4,2) that made row 4
    "interesting" was simply the wall sealing it.
    """

    def boxed_board(self):
        info = empty_grid()
        info[(3, 1)]["player"] = 0.2
        for cell in ((1, 1), (1, 4), (2, 0), (2, 1), (3, 2), (4, 2)):
            info[cell]["pyramid"] = 0.9
        return info

    def test_it_breaks_the_wall_instead_of_shuffling_into_the_pocket(self):
        action, reason = strategy.choose(self.boxed_board(), player=(3, 1))
        self.assertEqual(action[0], "attack",
                         f"shuffled instead of opening the way ({reason})")

    def test_a_row_that_can_be_advanced_from_still_attracts(self):
        # Same shape, but row 4 is open at column 2: stepping down is a
        # real lane change, and a free step must still beat a 200-shard
        # garra.
        info = self.boxed_board()
        info[(4, 2)]["pyramid"] = 0.0
        action, reason = strategy.choose(info, player=(3, 1))
        self.assertEqual((action[0], action[2]), ("move", "down"), reason)


class PerishableVetoNeedsAWayThereTests(unittest.TestCase):
    """Refusing to advance protects a prize only if the prize is gettable.

    Run 20260823T074036 n=197-199 ended the run ping-ponging (0,0)<->(0,1):
    the explorer wanted right, the column-0 veto forbade the scroll on
    behalf of a dash orb at (3,0), and row 1 was walled at columns 0 AND
    1 - so the orb was unreachable and the veto was protecting nothing at
    the price of every remaining paw.
    """

    def board_of_the_livelock(self):
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        for cell in ((1, 0), (1, 1), (3, 1), (3, 4)):
            info[cell]["pyramid"] = 0.9
        info[(3, 0)].update(item=0.10, green=0.10)      # dash orb
        return info

    def test_the_walled_off_perishable_does_not_veto_the_advance(self):
        info = self.board_of_the_livelock()
        action, reason = strategy.choose(info)
        self.assertIsNotNone(action)
        kind, target, direction = action
        self.assertNotEqual(direction, "left",
                            f"stepped backwards for an unreachable orb ({reason})")

    def test_the_bot_never_steps_back_onto_the_cell_it_just_left(self):
        # The ping-pong itself: from (0,0) the explorer goes right, and
        # from (0,1) it must not answer by going straight back.
        info = self.board_of_the_livelock()
        forward, _ = strategy.choose(info)
        self.assertNotEqual(forward[1], (0, 0))

    def test_a_reachable_perishable_still_stops_the_scroll(self):
        # The veto's real job survives: nothing walls off row 3 here, so
        # advancing would scroll a collectable orb off the board.
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        info[(3, 0)].update(item=0.10, green=0.10)
        action, reason = strategy.choose(info)
        kind, target, direction = action
        self.assertFalse(direction == "right" and target[1] >= 2,
                         f"scrolled a reachable orb away ({reason})")

    def test_a_perishable_behind_a_garra_does_not_veto_the_advance(self):
        # Reachable only by breaking a 200-shard pyramid: the veto must
        # not fire on its behalf. (The board deliberately holds no other
        # target - with one, plan_tour's cost-blind ordering answers
        # first and this stops testing the veto. That ordering is a
        # separate open question, written up in
        # docs/review-2026-08-23.md rather than pinned here.)
        info = empty_grid()
        info[(0, 1)]["player"] = 0.2
        for cell in ((1, 0), (1, 1), (3, 1)):
            info[cell]["pyramid"] = 0.9
        info[(3, 0)].update(item=0.10, green=0.10)
        # A dash orb three cells away behind a wall: prune_low_value_mids
        # keeps it out of the tour, so only the veto can speak.
        action, reason = strategy.choose(info)
        kind, target, direction = action
        self.assertNotEqual(direction, "left", reason)


if __name__ == "__main__":
    unittest.main()


class AdjacentGrabTests(unittest.TestCase):
    """An adjacent orange is never worth walking past.

    From 2026-08-24 to 2026-08-28 a guard skipped an adjacent plain
    orange whenever every other target sat back across the row it would
    leave, on the grounds that the two paws of the round trip cost more
    than the pickup. That arithmetic priced the orange at +20 energy,
    which was the passive regeneration tick and not the pickup at all.
    Re-measured over every recorded run (n=623 frames whose plan stepped
    onto a known orange) the pickup is +125, against 18.2 energy per
    charged step: the round trip pays about three and a half times over.

    Field case, run 20260828T150835 n=12 (user report): the bot took one
    orange of a vertical pair, the belt put the second one directly
    below it at (2,1), and the guard walked past it toward a dash orb on
    the player's own row. Two right steps later the orange had scrolled
    off the board.
    """

    def test_the_second_orange_of_a_pair_is_not_walked_past(self):
        info = empty_grid()
        info[(2, 1)].update(orange=.9, item=.9)
        info[(1, 4)].update(green=.9, item=.9)
        action, reason = strategy.choose(info, player=(1, 1),
                                         dashes_enabled=False)
        self.assertEqual(tuple(action[1]), (2, 1), reason)

    def test_the_orange_two_steps_away_is_still_approached(self):
        """One orange up and across, everything else below it."""
        info = empty_grid()
        for cell in ((1, 2), (3, 3), (4, 4)):
            info[cell].update(orange=.9, item=.9)
        action, reason = strategy.choose(info, player=(2, 1))
        self.assertEqual(tuple(action[1]), (1, 1), reason)

    def test_arriving_beside_it_takes_it(self):
        # The step that makes a target adjacent used to be the step that
        # pruned it, so the bot spent a paw to change its mind and often
        # a second one reversing. Nothing prunes it now.
        info = empty_grid()
        for cell in ((1, 2), (3, 3), (4, 4)):
            info[cell].update(orange=.9, item=.9)
        action, reason = strategy.choose(info, player=(1, 1))
        self.assertEqual(tuple(action[1]), (1, 2), reason)


class BarrenRevisitTests(unittest.TestCase):
    """Do not walk back onto a cell that already gave its answer.

    Measured over every recording (2026-08-28): 351 of 3062 cell changes
    return to a cell the player already stood on, with the belt in the
    same place and NOTHING collected in between - 351 paws, some 6400
    energy. 125 of 1346 vertical steps are reversed on the very next
    frame with the belt unmoved.

    All three terms matter. 1630 returns happen in total, so 1279 of them
    DID collect something: those are the round trip measured as 125
    energy for 36, and a rule that punished the bare return would ban it
    again - the guard retired earlier the same day, wearing a new hat.
    The runner clears the memory the moment the belt moves or a pickup
    lands, which is why the strategy can treat membership as final.
    """

    def board(self):
        """Right blocked, so the explorer has to pick a row."""
        info = empty_grid()
        for row in range(5):
            info[(row, 2)]["pyramid"] = 0.9
        return info

    def test_a_barren_cell_loses_to_a_fresh_one(self):
        info = self.board()
        up, _ = strategy.choose(info, player=(2, 1), attacks_enabled=False,
                                barren_cells={(3, 1)})
        self.assertEqual(tuple(up[1]), (1, 1))
        down, _ = strategy.choose(info, player=(2, 1), attacks_enabled=False,
                                  barren_cells={(1, 1)})
        self.assertEqual(tuple(down[1]), (3, 1))

    def test_without_the_memory_the_old_choice_stands(self):
        # The penalty must be the only thing that moved. On this board
        # the explorer prefers (3,1) on its own, so the test above is
        # meaningful in one direction and a no-op in the other: marking
        # (3,1) flips the verdict, marking (1,1) leaves it alone.
        plain, reason = strategy.choose(self.board(), player=(2, 1),
                                        attacks_enabled=False)
        self.assertEqual(tuple(plain[1]), (3, 1), reason)

    def test_a_fully_barren_board_still_moves(self):
        # A penalty, never a ban: in a cul-de-sac the only legal step IS
        # the one back, and refusing it would strand the run.
        info = self.board()
        action, reason = strategy.choose(
            info, player=(2, 1), attacks_enabled=False,
            barren_cells={(1, 1), (3, 1), (2, 0), (2, 2)})
        self.assertIsNotNone(action, reason)
        self.assertEqual(action[0], "move")

    def test_a_pickup_outranks_the_memory(self):
        # The memory only speaks in the explorer. A cell holding an item
        # is chosen by the branches above it, barren or not: the return
        # that collects something is the one worth 125 for 36.
        info = self.board()
        info[(3, 1)].update(orange=.9, item=.9)
        action, reason = strategy.choose(info, player=(2, 1),
                                         attacks_enabled=False,
                                         barren_cells={(3, 1)})
        self.assertEqual(tuple(action[1]), (3, 1), reason)


class PaidDetourAfterASecondReversalTests(unittest.TestCase):
    """The cost guard protects the wallet; it must not license a loop.

    Run 20260824T051703 n=38-40 (harness numbering): the player sat in a
    pocket walled by pyramids at (0,2), (1,2) and (2,1). The veto closed
    the cell it came from, the only answer on the closed board was a
    200-shard garra, the cost guard refused it - and the planner returned
    the reversal again. Three paws, five INDECISION/PING-PONG flags, and
    the loop only ended because the board moved on its own. A garra that
    ENDS the loop beats an unbounded run of 40-shard steps; one that
    merely avoids a single back-step does not.
    """

    def _pocket(self):
        info = empty_grid()
        for cell in ((0, 2), (1, 2), (2, 1)):
            info[cell]["pyramid"] = .9
        return info

    def test_the_first_veto_keeps_the_cheap_reversal(self):
        action, _ = strategy.choose(self._pocket(), None, player=(0, 1),
                                    blocked_direction="down")
        self.assertEqual(action, ("move", (1, 1), "down"))

    def test_a_repeated_reversal_buys_the_way_out(self):
        action, _ = strategy.choose(self._pocket(), None, player=(0, 1),
                                    blocked_direction="down",
                                    allow_paid_detour=True)
        self.assertNotEqual(action[0], "move")

    def test_the_flag_alone_changes_nothing_without_a_veto(self):
        free, _ = strategy.choose(self._pocket(), None, player=(0, 1))
        paid, _ = strategy.choose(self._pocket(), None, player=(0, 1),
                                  allow_paid_detour=True)
        self.assertEqual(free, paid)


class OverruleStreakTests(unittest.TestCase):
    """One overruled veto is an accident; two are a loop."""

    def test_a_veto_that_holds_resets_the_streak(self):
        self.assertEqual(runner.next_overrule_streak(2, "down", "right"), 0)

    def test_an_overruled_veto_counts(self):
        self.assertEqual(runner.next_overrule_streak(0, "down", "down"), 1)
        self.assertEqual(runner.next_overrule_streak(1, "down", "down"), 2)

    def test_no_veto_armed_says_nothing(self):
        self.assertEqual(runner.next_overrule_streak(2, None, "down"), 2)
