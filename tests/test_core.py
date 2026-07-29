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
        self.assertTrue(strategy.is_obstacle({"pyramid": 0.22, "item": 0.02}))

    def test_direct_horizontal_item_beats_distant_orange(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)].update(item=0.09, pink=0.09, pyramid=0.59)
        info[(4, 4)].update(item=0.10, orange=0.10)
        action, reason = strategy.choose(info, attacks_enabled=False)
        self.assertEqual(action, ("move", (2, 2), "right"))
        self.assertTrue(reason.startswith("direct horizontal item"))

    def test_blocked_right_route_uses_vertical_detour(self):
        info = empty_grid()
        info[(2, 1)]["player"] = 0.2
        info[(2, 2)]["pyramid"] = 0.25
        action, _ = strategy.choose(info, attacks_enabled=False,
                                    dashes_enabled=False)
        self.assertIn(action[2], ("up", "down"))


class BatchTests(unittest.TestCase):
    def test_batch_three_only_without_items(self):
        self.assertEqual(runner.adaptive_batch_limit(2, set()), 3)
        self.assertEqual(runner.adaptive_batch_limit(2, {(1, 4)}), 2)
        self.assertEqual(runner.adaptive_batch_limit(1, set()), 1)

    def test_followup_stops_before_pyramid(self):
        info = empty_grid()
        info[(2, 4)]["pyramid"] = 0.25
        moves = runner.safe_followup_moves(
            info, (2, 1), (2, 2), "right", 2, set()
        )
        self.assertEqual(moves, [((2, 2), (2, 3))])


if __name__ == "__main__":
    unittest.main()
