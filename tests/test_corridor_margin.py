"""The batching corridor: every blind tap must be safe under a swallowed tap.

The Android companion's planner guards this with `corridorClear`, which
demands the whole route plus one column of margin be free. This bot does
not need the margin - but only because of the belt arithmetic inside
`safe_followup_moves`, and that is exactly the kind of guarantee that
disappears silently when someone edits the offset math. So it is pinned
here as a property, not as an extra condition in the code.

Claim: when the game swallows `j` of the expected scrolls, the screen
cell tapped at step k holds the world cell `checked_cell(k) - j`, and
every such cell was validated by this function before the batch went out.
"""

import random
import unittest

import auto_digiworld_batch2 as runner


def grid(pyramids=()):
    cells = {}
    for row in range(5):
        for col in range(5):
            cells[(row, col)] = {"player": 0.0, "orange": 0.0, "pink": 0.0,
                                 "green": 0.0, "item": 0.0,
                                 "pyramid": .9 if (row, col) in pyramids
                                 else 0.0,
                                 "highlight": 1.0}
    return cells


class CorridorTests(unittest.TestCase):
    def test_stops_before_a_pyramid_in_the_batch(self):
        info = grid(pyramids={(2, 3)})
        moves = runner.safe_followup_moves(info, (2, 1), (2, 2), "right", 3)
        self.assertEqual(moves, [])

    def test_batches_a_free_row(self):
        moves = runner.safe_followup_moves(grid(), (2, 1), (2, 2), "right", 2)
        self.assertEqual([checked for _, checked in moves], [(2, 3), (2, 4)])

    def test_every_swallowed_scroll_lands_on_a_validated_cell(self):
        rng = random.Random(19)
        for _ in range(300):
            pyramids = {(rng.randrange(5), rng.randrange(5))
                        for _ in range(rng.randrange(4))}
            info = grid(pyramids)
            row = rng.randrange(5)
            player = (row, rng.choice((0, 1)))
            first_target = (row, player[1] + 1)
            if first_target in pyramids:
                continue
            moves = runner.safe_followup_moves(info, player, first_target,
                                               "right", 3)
            # What the batch proved free: the caller's own first target
            # plus every cell this function checked.
            validated = {first_target} | {checked for _, checked in moves}
            for _, checked in moves:
                for swallowed in range(0, checked[1] - first_target[1] + 1):
                    landed = (checked[0], checked[1] - swallowed)
                    self.assertIn(
                        landed, validated,
                        f"tap could land on unvalidated {landed} "
                        f"(pyramids={sorted(pyramids)}, player={player})")

    def test_a_pyramid_behind_the_route_never_enters_the_corridor(self):
        # The cell the chain would fall back onto after one swallowed
        # scroll is the previous step's checked cell; a pyramid there
        # already truncated the batch, so it can never be tapped.
        info = grid(pyramids={(1, 4)})
        moves = runner.safe_followup_moves(info, (1, 1), (1, 2), "right", 3)
        self.assertEqual([checked for _, checked in moves], [(1, 3)])


if __name__ == "__main__":
    unittest.main()
