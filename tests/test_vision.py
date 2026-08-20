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

    def test_dark_board_has_no_cross(self):
        info = {
            (row, col): {"player": 0.0, "orange": 0.0, "pink": 0.0, "green": 0.0,
                         "item": 0.0, "pyramid": 0.0, "highlight": 0.05}
            for row in range(5) for col in range(5)
        }
        self.assertIsNone(strategy.player_from_highlights(info))


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
