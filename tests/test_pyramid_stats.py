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
        values = {"pyramid": 0.25, "item": 0.02, "orange": 0.0, "pink": 0.0, "green": 0.0}
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
        info[(2, 2)]["pyramid"] = 0.25
        info[(2, 3)]["pyramid"] = 0.25
        info[(2, 4)].update(item=0.09, orange=0.09)
        report = runner.dash_path_report(info, (2, 1))
        self.assertEqual(report["pyramids"], 2)
        self.assertEqual(report["visible_items"], 1)
        self.assertEqual(report["cells_seen"], [[2, 2], [2, 3], [2, 4]])

    def test_path_is_clipped_at_board_edge(self):
        info = empty_grid()
        info[(0, 4)]["pyramid"] = 0.25
        report = runner.dash_path_report(info, (0, 3))
        self.assertEqual(report["pyramids"], 1)
        self.assertEqual(report["cells_seen"], [[0, 4]])


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
            {"pyramid_result": {"broken": True, "revealed": "orange"},
             "action": [{"type": "move", "target_cell": [2, 4]}]},
            {"pyramid_result": {"broken": True, "revealed": None},
             "action": "WAIT: overlay visible"},
            {"pyramid_result": {"broken": False, "revealed": None},
             "action": "STOP: no safe action"},
            {"action": [{"type": "dash"}],
             "dash_path": {"pyramids": 2, "visible_items": 1, "cells_seen": []}},
            {"dash_result": {"pyramids_in_path": 2, "visible_items_in_path": 1,
                             "energy_before": 100, "energy_after": 108,
                             "energy_delta": 8}},
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


if __name__ == "__main__":
    unittest.main()
