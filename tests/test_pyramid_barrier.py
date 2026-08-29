"""The board of run 20260829T170745, read from the frames themselves.

User report 2026-08-29: an unlogged session walked circles in front of a
pyramid barrier - "empezo a dar vueltas acercandose a la piramide ...
[0,3] -> [1,3] -> [1,2] -> [1,1] -> [0,1] -> [0,2] (era un loop amplio)".
The barrier the debug session opened on is the same one, and it is the
hardest shape the board can draw: every route right costs a garra.

    col      0     1     2     3     4   | 5 (the sliver)
    row 0    .     P     .     .     .   |  .
    row 1    .     .     P     .     .   |  .
    row 2    .     .     P     .     .   |  .
    row 3    .    bot    P     .     .   |  P
    row 4    .     P     .     P     .   |  .

Column 2 is walled on rows 1-3; the two ways around it, row 0 and row 4,
are corked at column 1. So there is no free path and never was - the
loop was not indecision, it was a bot whose garras had been switched off
walking the only cells left to it.
"""
import unittest
from pathlib import Path

from PIL import Image

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner


FIXTURES = Path(__file__).with_name("fixtures")
BOARD = (77, 424, 624, 875)
BOARD_AFTER = (77, 425, 624, 870)


def read(name, board):
    return strategy.cells(Image.open(FIXTURES / name).convert("RGB"), board)


class PyramidBarrierTests(unittest.TestCase):
    def setUp(self):
        self.info = read("pyramid_barrier.png", BOARD)
        self.after = read("pyramid_barrier_after_garra.png", BOARD_AFTER)
        self.player = (3, 1)

    def test_the_barrier_reads_as_the_user_described_it(self):
        seen = {cell for cell, values in self.info.items()
                if strategy.is_obstacle(values)}
        self.assertEqual(seen, {(0, 1), (1, 2), (2, 2), (3, 2), (4, 1), (4, 3)})

    def test_the_sliver_sees_the_pyramid_behind_the_wall(self):
        preview = strategy.sixth_column_preview(
            Image.open(FIXTURES / "pyramid_barrier.png").convert("RGB"), BOARD)
        self.assertEqual(preview, [False, False, False, True, False])

    def test_every_way_around_the_wall_is_corked(self):
        """The reason no amount of walking solves this board."""
        for row in (0, 4):
            self.assertTrue(strategy.is_obstacle(self.info[(row, 1)]),
                            f"row {row} was open at column 1")

    def test_the_bot_opens_the_wall_instead_of_walking_around_it(self):
        action, reason = strategy.choose(self.info, None, True, True,
                                         player=self.player)
        self.assertEqual(action[0], "attack")
        self.assertEqual(action[1], (3, 2), reason)

    def test_with_garras_off_there_is_nothing_but_walking(self):
        """What the user watched. Not a planning bug: with attacks
        disabled the board offers no move that reaches column 2, so
        whatever the bot picks is a step it will have to take back."""
        action, _ = strategy.choose(self.info, None, False, False,
                                    player=self.player)
        self.assertNotEqual(action[0], "attack")
        self.assertNotIn(action[1], {(3, 2), (4, 1)})

    def test_the_garra_that_landed_is_not_reported_dead(self):
        """n=0 tapped (3,2); n=1 shows it dissolving while the four
        pyramids it shares the screen with have not moved. Calling that
        "no visual effect" twice in a row is what switches garras off -
        and switching them off on this board is the loop.

        It used to read .93 -> .63, straddling the threshold, and only
        the drop rule saved it. Once the walkable highlight left the
        pyramid mask the same cell reads .55 -> .03: the bot is standing
        beside it, so most of what kept it "above the line" was the
        game lighting the cell as a legal move."""
        before, after = self.info[(3, 2)], self.after[(3, 2)]
        self.assertTrue(strategy.is_obstacle(before))
        self.assertFalse(strategy.is_obstacle(after))
        self.assertLess(after["pyramid"], before["pyramid"] - runner.BREAK_DROP)
        for cell in ((0, 1), (1, 2), (2, 2), (4, 1), (4, 3)):
            self.assertLess(abs(self.info[cell]["pyramid"]
                                - self.after[cell]["pyramid"]), .05, cell)
        self.assertTrue(runner.attack_result(after, before)["broken"])


class SixthColumnTuningTests(unittest.TestCase):
    """The retune is a threshold change; these pin what it must not lose.

    Ground truth for the sliver comes free from the runs: the strip IS
    column 5, so a one-column scroll turns it into column 4. Measured on
    4,845 labelled readings over 32 runs, picked on 21 and reported on
    the 11 held out (split by run): 0.941 precision / 0.916 recall,
    against 0.869 / 0.902 for the old .18-wide, +10-margin, >.5 strip.
    """

    def test_the_strip_still_refuses_a_frame_with_no_sliver(self):
        image = Image.open(FIXTURES / "pyramid_barrier.png").convert("RGB")
        width = image.size[0]
        self.assertIsNone(strategy.sixth_column_preview(
            image, (77, 424, width - 2, 875)))

    def test_the_wall_row_reads_the_same_after_the_garra(self):
        """Row 3 holds the incoming pyramid in both frames; an attack does
        not scroll, so the sliver must not change under it."""
        for name, board in (("pyramid_barrier.png", BOARD),
                            ("pyramid_barrier_after_garra.png", BOARD_AFTER)):
            preview = strategy.sixth_column_preview(
                Image.open(FIXTURES / name).convert("RGB"), board)
            self.assertEqual(preview, [False, False, False, True, False], name)


class WalkableHighlightTests(unittest.TestCase):
    """The game lights the cells you may step into. That light is bright
    blue, so it fed the very mask that detects pyramid glass: a cell the
    bot steps NEXT TO could spike for no other reason.

    Run 20260829T204601 n=21 (user: "decidio alejarse de una energia que
    justamente tiene una punta de piramide desde abajo"): a real orange
    at (3,2) with a pyramid at (4,2) below it read .067 on every frame
    but the one where the bot stood beside it - .468 there, with
    highlight .767 - and left the planner's board for it."""

    def test_the_lit_neighbour_does_not_read_as_glass(self):
        after = read("pyramid_barrier_after_garra.png", BOARD_AFTER)
        lit = after[(3, 2)]
        self.assertGreater(lit["highlight"], .60)
        self.assertLess(lit["pyramid"], strategy.PYRAMID_THRESHOLD)

    def test_a_real_pyramid_survives_losing_its_highlight(self):
        """Every pyramid on this board keeps its score with the light
        taken out. Over 1,139 recorded frames all 3,850 cells reading
        raw glass above .90 stay above .40 (worst .438)."""
        info = read("pyramid_barrier.png", BOARD)
        for cell in ((0, 1), (1, 2), (2, 2), (3, 2), (4, 1), (4, 3)):
            self.assertTrue(strategy.is_obstacle(info[cell]), cell)


class OneCellOneThingTests(unittest.TestCase):
    """User law 2026-08-29: "No puede haber mas de una cosa en cada
    celda. Las piramides no pueden tener items reales encima. Solo
    pueden aparecer items si se destruyen con un ataque."

    So a colour reading on a standing pyramid is confetti painted on it,
    and the pyramid wins. Which colour matters, and the RGB cube says
    why - swept exhaustively against this module's own glass test
    (`b > 70 and r > 45 and b > g + 10`):

        green  371,046 colours, of them glass       0  ( 0.00%)
        orange 123,950 colours, of them glass   4,921  ( 3.97%)
        pink   192,660 colours, of them glass 187,150  (97.14%)

    Pink IS glass; that is what the veto was built for and it keeps it.
    Green and orange are a different colour, so they were never the
    pixels that made the pyramid score high.
    """

    def test_confetti_colours_do_not_hide_a_pyramid(self):
        # Run 20260828T215949 n=77: a board mid-confetti-burst, glass
        # pyramids handed to the planner as pickups. 101 such cells in
        # 1,182 recorded frames.
        covered = {"pyramid": .99, "item": .085, "pink": .0,
                   "orange": .085, "green": .0, "claw": .0}
        self.assertTrue(strategy.is_obstacle(covered))
        self.assertIsNone(strategy.pickup_type(covered))

    def test_a_purple_ticket_is_still_not_a_pyramid(self):
        # Pink art IS pyramid glass by colour, so the veto stays.
        ticket = {"pyramid": .60, "item": .09, "pink": .09,
                  "orange": .0, "green": .0, "white": .06, "claw": .0}
        self.assertFalse(strategy.is_obstacle(ticket))
        self.assertEqual(strategy.pickup_type(ticket), "purple_ticket")

    def test_a_covered_pyramid_is_never_offered_as_a_goal(self):
        """The half that made the corpus flag STARVATION: `orange_items`
        and `other_items` read the raw colour scores, so the planner
        routed to a cell `unsafe_move_tap` then refused as a pyramid."""
        info = read("pyramid_barrier.png", BOARD)
        info[(3, 2)] = dict(info[(3, 2)], orange=.20, item=.20)
        self.assertTrue(strategy.is_obstacle(info[(3, 2)]))
        action, reason = strategy.choose(info, None, True, True,
                                         player=(3, 1))
        self.assertNotEqual((action[0], action[1]), ("move", (3, 2)), reason)


if __name__ == "__main__":
    unittest.main()
