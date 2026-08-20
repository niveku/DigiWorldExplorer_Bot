import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner


FIXTURES = Path(__file__).with_name("fixtures")

# Board colors: dark blue tile, pyramid glass (blue-violet, b > g by far).
TILE = (25, 60, 90)
PYRAMID = (100, 80, 180)


def board_image(paint):
    """500x500 board of 100px cells; paint(row, col) returns a color or None."""
    a = np.zeros((500, 500, 3), dtype=np.uint8)
    a[:, :] = TILE
    for row in range(5):
        for col in range(5):
            color = paint(row, col)
            if color:
                a[row*100:(row+1)*100, col*100:(col+1)*100] = color
    return a


class PyramidApexBleedTests(unittest.TestCase):
    def test_full_cell_pyramid_is_an_obstacle(self):
        image = board_image(lambda r, c: PYRAMID if (r, c) == (1, 2) else None)
        info = strategy.cells(image, (0, 0, 500, 500))
        self.assertTrue(strategy.is_obstacle(info[(1, 2)]))

    def test_apex_bleed_into_cell_above_is_not_an_obstacle(self):
        image = board_image(lambda r, c: PYRAMID if (r, c) == (1, 2) else None)
        # The pyramid's apex pokes deep into the bottom of the cell above,
        # like the tall glass pyramids do at 720x1280.
        image[60:100, 210:290] = PYRAMID
        info = strategy.cells(image, (0, 0, 500, 500))
        self.assertTrue(strategy.is_obstacle(info[(1, 2)]))
        self.assertFalse(strategy.is_obstacle(info[(0, 2)]))


class InventoryOcrTests(unittest.TestCase):
    def test_reads_the_final_frame_counters(self):
        image = Image.open(FIXTURES / "hud_29_74_32.png")
        self.assertEqual(runner.read_inventory_counters(image),
                         {"steps": 29, "attacks": 74, "dashes": 32})

    def test_reads_the_check_frame_counters(self):
        image = Image.open(FIXTURES / "hud_31_3_1.png")
        self.assertEqual(runner.read_inventory_counters(image),
                         {"steps": 31, "attacks": 3, "dashes": 1})

    def test_reads_garra_counter_in_the_fifties(self):
        # Runs 20260820T030138/030401 lost every garra verification because
        # the game's "5" glyph matched the template '3' within the 0.04
        # margin; the real frame showing 59 garras is the regression anchor.
        image = Image.open(FIXTURES / "hud_127_59_25.png")
        self.assertEqual(runner.read_inventory_counters(image),
                         {"steps": 127, "attacks": 59, "dashes": 25})

    def test_pickup_types_are_distinguished(self):
        # Run 20260820T041234 proved the HUD counters move differently per
        # pickup: paws +5 steps, dash orb +1 dash, tickets +1 each. The
        # user-flagged confusion: paws and the purple ticket both read as
        # 'pink', the dash orb and the green ticket both as 'green'. The
        # separators: white card body (ticket 0.096 vs paws 0.002) and
        # saturated card green (ticket 0.089 vs orb 0.000).
        cases = [
            ("pickup_dash_orb.png", (77, 424, 625, 875), (3, 4), "dash_orb"),
            ("pickup_green_ticket.png", (74, 424, 625, 875), (0, 4), "green_ticket"),
            ("pickup_paws.png", (77, 426, 625, 871), (3, 4), "steps"),
            ("pickup_purple_ticket.png", (77, 336, 625, 783), (4, 4), "purple_ticket"),
        ]
        for name, board, cell, expected in cases:
            with self.subTest(pickup=expected):
                info = strategy.cells(Image.open(FIXTURES / name), board)
                self.assertEqual(strategy.pickup_type(info[cell]), expected)

    def test_claw_and_orange_pickup_types(self):
        info = strategy.cells(Image.open(FIXTURES / "claw_board.png"),
                              (74, 425, 626, 871))
        self.assertEqual(strategy.pickup_type(info[(0, 3)]), "claw")
        self.assertEqual(strategy.pickup_type(info[(3, 3)]), "orange")
        self.assertIsNone(strategy.pickup_type(info[(1, 4)]))

    def test_milestone_chest_badge_signals_a_claim(self):
        # User captures 2026-08-20: at each 1,000m milestone the chest by
        # the progress bar gains a magenta '!' badge. After claiming, the
        # chest stays golden but the badge disappears - the badge, not the
        # gold, is the claim signal.
        image = Image.open(FIXTURES / "chest_ready.png")
        point = runner.milestone_chest_ready(image)
        self.assertIsNotNone(point)
        x, y = point
        self.assertAlmostEqual(x / image.width, 0.76, delta=0.04)
        self.assertAlmostEqual(y / image.height, 0.715, delta=0.03)

    def test_tap_point_ignores_the_gold_meters_text(self):
        # Run 20260820T192556 event 240: tap_xy (379, 912) on a 720-wide
        # frame while the chest sits around x=510. The old tap point
        # averaged gold AND badge pixels, and the golden "12,000m" text
        # dragged the centroid ~130px left onto the bar: the tap opened
        # nothing and close_reward_overlay reported instant "success".
        # The badge rides the chest, so the tap point is badge-only -
        # extra gold far from the chest must not move it.
        image = Image.open(FIXTURES / "chest_ready.png").convert("RGB")
        base = runner.milestone_chest_ready(image)
        a = np.asarray(image).copy()
        h = a.shape[0]
        # Paint a fat block of gold "text" at the left of the badge band.
        a[int(h*.70):int(h*.73), 40:200] = (250, 190, 60)
        polluted = runner.milestone_chest_ready(Image.fromarray(a))
        self.assertIsNotNone(polluted)
        self.assertAlmostEqual(polluted[0], base[0], delta=3)
        self.assertAlmostEqual(polluted[1], base[1], delta=3)

    def test_claimed_chest_without_badge_is_not_retapped(self):
        image = Image.open(FIXTURES / "chest_claimed.png")
        self.assertIsNone(runner.milestone_chest_ready(image))

    def test_reset_chest_is_ignored(self):
        image = Image.open(FIXTURES / "chest_reset.png")
        self.assertIsNone(runner.milestone_chest_ready(image))

    def test_ordinary_board_frame_shows_no_claim(self):
        image = Image.open(FIXTURES / "claw_board.png")
        self.assertIsNone(runner.milestone_chest_ready(image))

    def test_claw_pickup_gets_its_own_score(self):
        # Live capture 2026-08-20: claw pickup at (0,3) (yellow slashes on a
        # dark disc, RGB ~254,223,50). The generic item score only reached
        # 0.023, below the 0.06 threshold, so the bot skipped every claw.
        # The orange energy's white bolt must stay below the claw threshold.
        image = Image.open(FIXTURES / "claw_board.png")
        info = strategy.cells(image, (74, 425, 626, 871))
        self.assertGreater(info[(0, 3)]["claw"], 0.10)
        self.assertLess(info[(3, 3)]["claw"], 0.10)    # orange energy bolt
        self.assertLess(info[(1, 4)]["claw"], 0.005)   # empty dark cell
        self.assertLess(info[(0, 2)]["claw"], 0.005)   # pyramid

    def test_energy_counter_still_reads_after_font_changes(self):
        image = Image.open(FIXTURES / "hud_29_74_32.png")
        self.assertEqual(runner.read_energy_counter(image), 5760)

    def test_reads_ticket_counters_final_frame(self):
        image = Image.open(FIXTURES / "hud_29_74_32.png")
        self.assertEqual(runner.read_ticket_counters(image),
                         {"green": 28954, "purple": 28956})

    def test_reads_ticket_counters_check_frame(self):
        image = Image.open(FIXTURES / "hud_31_3_1.png")
        self.assertEqual(runner.read_ticket_counters(image),
                         {"green": 28954, "purple": 28954})

    def test_drop_counters_merge_inventory_and_tickets(self):
        image = Image.open(FIXTURES / "hud_29_74_32.png")
        self.assertEqual(runner.read_drop_counters(image),
                         {"steps": 29, "attacks": 74, "dashes": 32,
                          "green_tickets": 28954, "purple_tickets": 28956})


RED_ARMOR = (200, 40, 50)


class LargePlayerTests(unittest.TestCase):
    def test_real_fm_frame_is_located_on_its_cell(self):
        import digiworld_bot as bot
        image = Image.open(FIXTURES / "fm_at_3_1.png")
        det = bot.classify(image)
        located = strategy.find_large_player(np.asarray(image.convert("RGB")), det.board)
        self.assertIsNotNone(located)
        self.assertEqual(located[0], (3, 1))

    def test_top_row_sprite_overflowing_the_board_is_still_found(self):
        import digiworld_bot as bot
        image = Image.open(FIXTURES / "fm_at_0_1.png")
        det = bot.classify(image)
        located = strategy.find_large_player(np.asarray(image.convert("RGB")), det.board)
        self.assertIsNotNone(located)
        self.assertEqual(located[0], (0, 1))

    def test_orange_items_do_not_stretch_the_blob(self):
        import digiworld_bot as bot
        image = Image.open(FIXTURES / "fm_at_1_1.png")
        det = bot.classify(image)
        located = strategy.find_large_player(np.asarray(image.convert("RGB")), det.board)
        self.assertIsNotNone(located)
        self.assertEqual(located[0], (1, 1))

    def test_oversized_sprite_is_anchored_at_its_feet(self):
        image = board_image(lambda r, c: None)
        # A 2x2.3-cell red sprite like Imperialdramon FM centered on col 1,
        # feet in row 3.
        image[150:380, 60:200] = RED_ARMOR
        located = strategy.find_large_player(image, (0, 0, 500, 500))
        self.assertIsNotNone(located)
        cell, score = located
        self.assertEqual(cell, (3, 1))
        self.assertGreaterEqual(score, 0.08)

    def test_red_card_shading_in_item_cells_is_ignored(self):
        image = board_image(lambda r, c: None)
        image[150:380, 60:200] = RED_ARMOR          # FM around (1-3, 1)
        image[330:370, 320:360] = (200, 50, 30)     # dark-red item card edge at (3, 3)
        with_ghost = strategy.find_large_player(image, (0, 0, 500, 500))
        clean = strategy.find_large_player(image, (0, 0, 500, 500),
                                           item_cells={(3, 3)})
        self.assertIsNotNone(clean)
        self.assertEqual(clean[0], (3, 1))

    def test_straddling_orange_cards_are_not_a_player(self):
        # Run 20260820T192556 event 191: two orange cards sliding across
        # the (2,0)/(2,1) border formed a 0.027-score red blob. The blob
        # was taken as an oversized player, suppress_sprite_leaks wiped
        # the 3x3 around it - deleting two real oranges from the map -
        # and the scroll then ate one of them. Per-cell masking cannot
        # catch a card that straddles cells; a score floor can: a real
        # oversized sprite (FM) scores ~0.1+, card slivers stay below.
        import digiworld_bot as bot
        image = Image.open(FIXTURES / "phantom_blob_cards.png")
        det = bot.classify(image)
        info = strategy.cells(np.asarray(image.convert("RGB")), det.board)
        item_cells = {cell for cell, v in info.items() if v["item"] > .06}
        located = strategy.find_large_player(
            np.asarray(image.convert("RGB")), det.board, item_cells=item_cells)
        self.assertIsNone(located)

    def test_a_few_stray_pixels_are_not_a_player(self):
        image = board_image(lambda r, c: None)
        image[200:205, 100:110] = RED_ARMOR
        self.assertIsNone(strategy.find_large_player(image, (0, 0, 500, 500)))

    def test_board_wide_noise_is_rejected(self):
        image = board_image(lambda r, c: None)
        image[10:490:12, :] = RED_ARMOR
        self.assertIsNone(strategy.find_large_player(image, (0, 0, 500, 500)))


class HighlightCrossTests(unittest.TestCase):
    def cells_for(self, name):
        import digiworld_bot as bot
        image = Image.open(FIXTURES / name)
        det = bot.classify(image)
        return strategy.cells(np.asarray(image.convert("RGB")), det.board)

    def test_finds_gatomon_from_movable_cell_cross(self):
        info = self.cells_for("hud_29_74_32.png")
        self.assertEqual(strategy.player_from_highlights(info), (1, 1))

    def test_finds_botamon_from_movable_cell_cross(self):
        info = self.cells_for("hud_31_3_1.png")
        self.assertEqual(strategy.player_from_highlights(info), (4, 1))

    def test_cross_far_from_expected_position_is_rejected(self):
        info = {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 0.0}
            for row in range(5) for col in range(5)
        }
        for cell in ((0, 3), (1, 4)):  # lit patch far away from the player
            info[cell]["highlight"] = 1.0
        self.assertEqual(strategy.player_from_highlights(info), (0, 4))
        self.assertIsNone(strategy.player_from_highlights(info, expected=(3, 1)))

    def test_dark_board_has_no_cross(self):
        info = {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 0.05}
            for row in range(5) for col in range(5)
        }
        self.assertIsNone(strategy.player_from_highlights(info))


class BlobVetoTests(unittest.TestCase):
    def test_weak_vision_yields_to_the_blob(self):
        result = runner.veto_with_blob((3, 3), 0.05, "vision", ((1, 1), 0.10))
        self.assertEqual(result, ((1, 1), 0.10, "large-sprite"))

    def test_marginal_vision_far_from_a_blob_is_a_false_positive(self):
        result = runner.veto_with_blob((3, 3), 0.095, "vision", ((1, 1), 0.10))
        self.assertEqual(result, ((1, 1), 0.10, "large-sprite"))

    def test_confident_vision_survives_a_distant_blob(self):
        result = runner.veto_with_blob((3, 3), 0.22, "vision", ((1, 1), 0.10))
        self.assertEqual(result, ((3, 3), 0.22, "vision"))

    def test_torso_vision_one_cell_above_the_blob_yields_to_it(self):
        result = runner.veto_with_blob((2, 1), 0.11, "vision", ((3, 1), 0.11))
        self.assertEqual(result, ((3, 1), 0.11, "large-sprite"))

    def test_memory_yields_to_fresh_blob_evidence(self):
        result = runner.veto_with_blob((2, 1), 0.05, "memory", ((1, 1), 0.10))
        self.assertEqual(result, ((1, 1), 0.10, "large-sprite"))

    def test_memory_without_a_blob_still_bridges(self):
        result = runner.veto_with_blob((2, 1), 0.05, "memory", None)
        self.assertEqual(result, ((2, 1), 0.05, "memory"))

    def test_no_blob_changes_nothing(self):
        result = runner.veto_with_blob((3, 3), 0.05, "vision", None)
        self.assertEqual(result, ((3, 3), 0.05, "vision"))


class ResolvedPlayerOverrideTests(unittest.TestCase):
    def test_choose_trusts_an_externally_resolved_player(self):
        info = grid_with_player((0, 0), 0.0)  # no per-cell score anywhere
        action, reason = strategy.choose(info, player=(3, 1))
        self.assertIsNotNone(action)
        self.assertEqual(reason, "explore right")

    def test_choose_still_rejects_weak_frames_without_override(self):
        info = grid_with_player((0, 0), 0.0)
        action, reason = strategy.choose(info)
        self.assertIsNone(action)


class SpriteLeakSuppressionTests(unittest.TestCase):
    def grid(self):
        return {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 0.2}
            for row in range(5) for col in range(5)
        }

    def test_items_around_a_big_sprite_are_wiped(self):
        info = self.grid()
        info[(1, 1)].update(item=0.20, orange=0.20)   # wing leak above player
        info[(2, 2)].update(item=0.15, pink=0.15)     # wing leak beside player
        info[(4, 4)].update(item=0.10, green=0.10)    # real distant item
        cleaned = strategy.suppress_sprite_leaks(info, (2, 1))
        self.assertEqual(cleaned[(1, 1)]["item"], 0.0)
        self.assertEqual(cleaned[(2, 2)]["orange"], 0.0)
        self.assertEqual(cleaned[(4, 4)]["item"], 0.10)

    def test_pyramids_and_highlights_survive(self):
        info = self.grid()
        info[(1, 1)].update(pyramid=0.30, highlight=0.9, item=0.2)
        cleaned = strategy.suppress_sprite_leaks(info, (2, 1))
        self.assertEqual(cleaned[(1, 1)]["pyramid"], 0.30)
        self.assertEqual(cleaned[(1, 1)]["highlight"], 0.9)


class SixthColumnTests(unittest.TestCase):
    def test_preview_flags_the_incoming_pyramid_row(self):
        image = np.zeros((500, 540, 3), dtype=np.uint8)
        image[:, :] = TILE
        # Board occupies x 0..500; the sliver 500..540 shows column 5.
        image[100:180, 502:538] = PYRAMID   # incoming pyramid in row 1
        preview = strategy.sixth_column_preview(image, (0, 0, 500, 500))
        self.assertEqual(preview, [False, True, False, False, False])

    def test_no_sliver_room_means_no_preview(self):
        image = np.zeros((500, 502, 3), dtype=np.uint8)
        image[:, :] = TILE
        self.assertIsNone(strategy.sixth_column_preview(image, (0, 0, 500, 500)))


class PreviewWallTests(unittest.TestCase):
    def grid(self):
        return {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 1.0}
            for row in range(5) for col in range(5)
        }

    def test_two_wall_at_the_edge_plus_preview_is_a_dash_wall(self):
        info = self.grid()
        info[(1, 3)]["pyramid"] = 0.9
        info[(1, 4)]["pyramid"] = 0.9
        preview = [False, True, False, False, False]
        self.assertIsNone(strategy.nearest_dash_wall(info, (1, 0)))
        self.assertEqual(strategy.nearest_dash_wall(info, (1, 0), preview=preview),
                         (1, 2))

    def test_preview_elsewhere_does_not_fake_walls(self):
        info = self.grid()
        info[(1, 3)]["pyramid"] = 0.9
        info[(1, 4)]["pyramid"] = 0.9
        preview = [True, False, False, False, False]
        self.assertIsNone(strategy.nearest_dash_wall(info, (1, 0), preview=preview))


class ExpectedPositionTests(unittest.TestCase):
    def test_right_move_into_scroll_zone_lands_one_left(self):
        self.assertEqual(runner.expected_after_move((2, 2), "right"), (2, 1))

    def test_right_move_before_scroll_zone_lands_on_target(self):
        self.assertEqual(runner.expected_after_move((2, 1), "right"), (2, 1))

    def test_vertical_move_lands_on_target(self):
        self.assertEqual(runner.expected_after_move((3, 1), "down"), (3, 1))


def grid_with_player(cell, score, extra=()):
    info = {
        (row, col): {
            "player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
            "item": 0.0, "pyramid": 0.0, "highlight": 1.0,
        }
        for row in range(5) for col in range(5)
    }
    info[cell]["player"] = score
    for other_cell, other_score in extra:
        info[other_cell]["player"] = other_score
    return info


class ResolvePlayerTests(unittest.TestCase):
    def test_strong_vision_wins(self):
        info = grid_with_player((2, 2), 0.30)
        cell, score, source = runner.resolve_player(info, expected=(2, 1))
        self.assertEqual((cell, source), ((2, 2), "vision"))

    def test_impossible_jump_is_vetoed_by_memory(self):
        info = grid_with_player((4, 4), 0.12, extra=[((2, 1), 0.05)])
        cell, score, source = runner.resolve_player(info, expected=(2, 1))
        self.assertEqual((cell, source), ((2, 1), "memory-veto"))

    def test_weak_vision_falls_back_to_memory(self):
        info = grid_with_player((0, 1), 0.04, extra=[((1, 1), 0.03)])
        cell, score, source = runner.resolve_player(info, expected=(1, 1))
        self.assertEqual((cell, source), ((1, 1), "memory"))

    def test_weak_vision_without_memory_stays_weak_vision(self):
        info = grid_with_player((0, 1), 0.04)
        cell, score, source = runner.resolve_player(info, expected=None)
        self.assertEqual(source, "vision")
        self.assertLess(score, 0.08)


if __name__ == "__main__":
    unittest.main()
