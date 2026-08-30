"""The world model: tracked entities instead of six suspicion holds.

Design mandate (user, 2026-08-22, after the multi-agent overengineering
review): stop re-deciding what every cell is on every frame. Know what
is being built from the RIGHT, carry it in memory through its
confirmation stages, avoid reprocessing, and use it to PLAN.

The model that replaces the stack:
  - every detected entity is a TRACK with an identity that survives the
    scroll (the pixel sensor measures it) and survives being covered;
  - a NEW track is classified ONCE by its origin - a right-edge entry
    consistent with the measured scroll, a garra reveal, or the start
    of the run are real; anything else is confetti, which cannot
    outlive two settled frames;
  - suspicion is one property of a track, not six overlapping holds;
  - the sixth-column preview feeds a pipeline of what is coming, so the
    planner can position BEFORE the wall lands.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import world_model as wm

MAX_MISSES_FOR_TEST = wm.MAX_MISSES


def seen(items=(), pyramids=()):
    """A frame's detections: item cells (with category) and pyramids."""
    return {"items": dict(items), "pyramids": set(pyramids)}


def running():
    """A model past its opening frame.

    The first observation IS the world as given - there is no previous
    frame it could have scrolled in from - so any test about how an
    entity ARRIVED has to start from a board already being watched."""
    world = wm.WorldModel()
    world.observe(seen(), shift=0)
    return world


class TrackIdentityTests(unittest.TestCase):
    """A track keeps its identity across the scroll and across being
    covered. This single property removes the whole class of bugs the
    old stack fought one at a time: the flicker that reset the sticky
    clock, the carryover that vanished across a scroll, the covered
    item that reappeared as an 'unexplained arrival'."""

    def test_track_follows_the_measured_scroll(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        world.observe(seen(items={(2, 3): "orange"}), shift=1)
        track = world.at((2, 3))
        self.assertIsNotNone(track)
        self.assertEqual(track.sightings, 2)
        self.assertEqual(track.origin, "right_edge")

    def test_a_covered_frame_does_not_restart_the_track(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        world.observe(seen(items={(2, 3): "orange"}), shift=1)
        world.observe(seen(), shift=0)          # confetti covers it
        world.observe(seen(items={(2, 3): "orange"}), shift=0)
        track = world.at((2, 3))
        self.assertEqual(track.sightings, 3)
        self.assertEqual(track.misses, 0)

    def test_a_track_unseen_too_long_is_forgotten(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        for _ in range(3):
            world.observe(seen(), shift=0)
        self.assertIsNone(world.at((2, 4)))


class OcclusionTests(unittest.TestCase):
    """Not seeing is not the same as not being there. An oversized
    partner's body covers whole cells for many frames, and its colours
    are wiped from those cells precisely because they read as false
    pickups - so what is underneath is UNOBSERVABLE, not absent. An
    occluded track neither ages nor gains confidence."""

    def test_occluded_track_does_not_age(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        for _ in range(5):
            world.observe(seen(), shift=0, occluded={(2, 4)})
        track = world.at((2, 4))
        self.assertIsNotNone(track)
        self.assertEqual(track.misses, 0)

    def test_occlusion_does_not_confirm_anything(self):
        world = running()
        world.observe(seen(items={(3, 1): "orange"}), shift=0)   # confetti
        for _ in range(4):
            world.observe(seen(), shift=0, occluded={(3, 1)})
        self.assertNotIn((3, 1), world.believed_items())


class OriginClassificationTests(unittest.TestCase):
    """Classified once, at birth, from physics: items enter only from
    the right edge as the world scrolls, or where a garra broke a
    pyramid. Everything else is animation residue."""

    def test_right_edge_entry_consistent_with_the_scroll_is_real(self):
        world = running()
        # Three scrolls: an entry can have travelled from column 4 to 2.
        world.observe(seen(items={(3, 2): "orange"}), shift=3)
        self.assertEqual(world.at((3, 2)).origin, "right_edge")
        self.assertIn((3, 2), world.believed_items())

    def test_mid_board_appearance_without_a_scroll_is_confetti(self):
        """Stated against the constant, not against a frame count: the
        number was re-priced on 2026-08-29 once BURST_ITEMS gave the
        model a causal confetti detector, and the principle - an
        unexplained birth has to outlive the animation - is what this
        test is for."""
        world = running()
        for _ in range(wm.CONFIRM_SIGHTINGS - 1):
            world.observe(seen(items={(3, 1): "orange"}), shift=0)
        self.assertEqual(world.at((3, 1)).origin, "unexplained")
        self.assertNotIn((3, 1), world.believed_items())

    def test_confetti_that_outlives_the_doubt_is_believed(self):
        world = running()
        for _ in range(wm.CONFIRM_SIGHTINGS):
            world.observe(seen(items={(3, 1): "orange"}), shift=0)
        self.assertIn((3, 1), world.believed_items())

    def test_garra_reveal_is_real_immediately(self):
        world = running()
        world.observe(seen(items={(2, 2): "orange"}), shift=0,
                      revealed={(2, 2)})
        self.assertEqual(world.at((2, 2)).origin, "reveal")
        self.assertIn((2, 2), world.believed_items())

    def test_the_opening_frame_is_the_world_as_given(self):
        world = wm.WorldModel()
        world.observe(seen(items={(0, 1): "orange", (4, 3): "claw"}),
                      shift=0)
        self.assertEqual(world.believed_items(),
                         {(0, 1): "orange", (4, 3): "claw"})


class PyramidsSurviveTheirCoverTests(unittest.TestCase):
    """A pyramid does not become a pickup because a card was painted
    over it. Run 20260822T160202 n=89: confetti covered a pyramid, the
    cell read as an item, and the move tap onto it executed a hidden
    200-shard garra. The old answer was to treat every suspect cell as
    impassable ground, which invented walls out of harmless confetti
    (run 20260823T033159: eight taps where six sufficed). The precise
    answer is that a pyramid only leaves by being broken or by
    scrolling off, so the track stays and the cell stays impassable
    for the ordinary reason: it is a pyramid."""

    def test_confetti_over_a_pyramid_does_not_replace_it(self):
        world = running()
        world.observe(seen(pyramids={(1, 1)}), shift=0)
        world.observe(seen(items={(1, 1): "orange"}), shift=0)
        self.assertIn((1, 1), world.believed_pyramids())
        self.assertNotIn((1, 1), world.believed_items())

    def test_a_cover_that_never_lifts_is_not_a_cover(self):
        """Run 20260829T201007 n=73-81 (user: "no recogio una energia, es
        como si se hubiera descachado"). The pyramid at (1,4) left the
        screen at n=73 and an orange took the cell. Being "seen" as an
        item kept the dead track out of the decay pass, so it never
        aged - it rode the belt left, (1,4) -> (1,3) -> (1,2), and the
        covered-pyramid merge stamped pyramid=.9 over a REAL orange one
        step from the bot. The planner walked away and spent four paws
        coming back.

        Confetti does not last: 87.8% of interior pickup sightings are
        gone by the next frame and 95.4% within two (709 quiet frame
        pairs). An item still there on the third frame is an item."""
        world = running()
        world.observe(seen(pyramids={(1, 4)}), shift=0)
        self.assertIn((1, 4), world.believed_pyramids())
        for frame in range(1, wm.MAX_MISSES):
            world.observe(seen(items={(1, 4): "orange"}), shift=0)
            self.assertIn((1, 4), world.believed_pyramids(),
                          f"gave up after {frame} covered frame(s)")
        world.observe(seen(items={(1, 4): "orange"}), shift=0)
        self.assertNotIn((1, 4), world.believed_pyramids())
        self.assertEqual(world.believed_items(), {(1, 4): "orange"})

    def test_a_cover_that_lifts_leaves_the_pyramid_intact(self):
        """The case this must not break: one frame of confetti, then the
        glass again (run 20260822T160202 n=89)."""
        world = running()
        world.observe(seen(pyramids={(1, 1)}), shift=0)
        world.observe(seen(items={(1, 1): "orange"}), shift=0)
        world.observe(seen(pyramids={(1, 1)}), shift=0)
        self.assertIn((1, 1), world.believed_pyramids())
        for _ in range(wm.MAX_MISSES + 1):
            world.observe(seen(items={(1, 1): "orange"}), shift=0)
            world.observe(seen(pyramids={(1, 1)}), shift=0)
        self.assertIn((1, 1), world.believed_pyramids())

    def test_a_broken_pyramid_leaves_at_once(self):
        # Vision reading the cell as plain empty is the break: pyramids
        # score 0.88-0.99, they do not flicker like items do.
        world = running()
        world.observe(seen(pyramids={(1, 1)}), shift=0)
        world.observe(seen(), shift=0)
        self.assertNotIn((1, 1), world.believed_pyramids())

    def test_a_real_drop_on_a_broken_pyramid_cell_is_believed(self):
        world = running()
        world.observe(seen(pyramids={(1, 1)}), shift=0)
        world.observe(seen(), shift=0)                      # garra broke it
        world.observe(seen(items={(1, 1): "orange"}), shift=0,
                      revealed={(1, 1)})
        self.assertIn((1, 1), world.believed_items())


class BeliefIsNotRelitigatedTests(unittest.TestCase):
    """Run 20260822T194747 n=20 (four-skip starvation, two energies
    lost): a remembered orange whose cell flickered suspect had its
    route refused four times in a row. The old stack needed a rule -
    'memory outranks suspicion' - plus a tap-gate exemption to undo
    what its own stages kept re-deciding. Here it is structural: a
    believed track that goes under confetti and comes back is the same
    track, so there is nothing to re-decide."""

    def test_a_believed_track_is_never_re_suspected(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        self.assertIn((2, 4), world.believed_items())
        world.observe(seen(), shift=0)                    # covered
        world.observe(seen(items={(2, 4): "orange"}), shift=0)
        self.assertIn((2, 4), world.believed_items())
        self.assertNotIn((2, 4), world.suspect_cells())

    def test_confetti_never_becomes_memory_by_being_covered(self):
        """A sighting that DIED counts for nothing: the track is dropped
        and the next one starts over. Written with one fewer sighting
        than belief needs, so it stays about the reset and not about the
        size of CONFIRM_SIGHTINGS."""
        world = running()
        for _ in range(wm.CONFIRM_SIGHTINGS - 1):
            world.observe(seen(items={(3, 1): "orange"}), shift=0)
        for _ in range(MAX_MISSES_FOR_TEST):
            world.observe(seen(), shift=0)                # gone
        world.observe(seen(items={(3, 1): "orange"}), shift=0)
        self.assertNotIn((3, 1), world.believed_items())


class ConfettiTests(unittest.TestCase):
    """Confetti, stated the way the game makes it (user law 2026-08-29).

    It exists only where something was just collected - a step onto a
    pickup, or a dash, which sweeps its whole lane and so always
    collects. Nowhere else. And it is only ever noise ADDED: it paints
    new cards over the board, it never removes what is there.

    So the signal is the CAUSE, not the crowd. Measured against the
    game's own energy counter over 916 recorded steps onto a cell the
    board showed as an orange:

        >=4 items, nothing collected in 3 frames :   4 real,   0 fake
        >=4 items, collected on the last frame   :  60 real, 240 fake
        <=3 items, nothing collected in 3 frames :  31 real,   1 fake
        <=3 items, collected on the last frame   : 541 real,  36 fake

    A crowded board with no collection behind it was real every single
    time - counting items punished exactly the frames worth having.
    """

    def test_a_rich_board_with_no_collection_behind_it_is_believed(self):
        """Run 20260829T234223 n=421: three oranges and a steps card on
        screen at once, energy flat for three frames, and the bot
        refused all four and walked past them."""
        world = running()
        rich = {(0, 2): "orange", (1, 3): "orange",
                (3, 4): "orange", (4, 2): "steps"}
        for _ in range(wm.CONFIRM_SIGHTINGS):
            world.observe(seen(items=rich), shift=0, collected=False)
        self.assertEqual(set(world.believed_items()), set(rich))
        self.assertEqual(world.suspect_cells(), set())

    def test_a_collection_frame_refuses_what_is_new(self):
        world = running()
        cards = {(r, 1): "orange" for r in range(4)}
        world.observe(seen(items=cards), shift=0, collected=True)
        self.assertEqual(world.believed_items(), {})
        self.assertEqual(world.suspect_cells(), set(cards))

    def test_what_was_already_known_survives_the_confetti(self):
        """The half the user asked for by name: the bot must go and get
        what it already knows is there. Confetti cannot make a real
        pickup vanish, so it must not make the model forget one."""
        world = running()
        for _ in range(wm.CONFIRM_SIGHTINGS):
            world.observe(seen(items={(0, 4): "orange"}), shift=1)
        self.assertIn((0, 4), world.believed_items())
        cards = {(r, 1): "orange" for r in range(4)}
        cards[(0, 4)] = "orange"
        world.observe(seen(items=cards), shift=0, collected=True)
        self.assertIn((0, 4), world.believed_items())
        self.assertNotIn((0, 4), world.suspect_cells())

    def test_a_known_item_does_not_age_under_the_confetti(self):
        world = running()
        for _ in range(wm.CONFIRM_SIGHTINGS):
            world.observe(seen(items={(0, 4): "orange"}), shift=1)
        cards = {(r, 1): "orange" for r in range(4)}
        cards[(0, 4)] = "orange"
        for _ in range(wm.MAX_MISSES + 2):
            world.observe(seen(items=cards), shift=0, collected=True)
        self.assertIn((0, 4), world.believed_items())

    def test_the_edge_still_delivers_during_a_collection(self):
        """A scroll and a pickup can land on the same frame. Column 4 is
        the board's door and stays open: refusing it would drop real
        arrivals every time the bot walks onto something."""
        world = running()
        world.observe(seen(items={(2, 4): "orange", (2, 1): "orange"}),
                      shift=1, collected=True)
        self.assertIn((2, 4), world.believed_items())
        self.assertNotIn((2, 1), world.believed_items())

    def test_a_dash_leaves_the_far_columns_in_doubt(self):
        """A dash scrolls three columns AND collects, so columns 2-4 are
        both newly arrived and freshly littered. That is the one case
        worth holding a frame for."""
        world = running()
        world.observe(seen(items={(1, 2): "orange", (1, 3): "orange",
                                  (1, 4): "orange"}),
                      shift=3, collected=True, edge_explains=False)
        self.assertEqual(world.believed_items(), {})
        self.assertEqual(world.suspect_cells(), {(1, 2), (1, 3), (1, 4)})

    def test_confetti_says_nothing_about_pyramids(self):
        world = running()
        cards = {(r, 1): "orange" for r in range(4)}
        world.observe(seen(items=cards, pyramids={(2, 3)}), shift=0,
                      collected=True)
        self.assertIn((2, 3), world.believed_pyramids())


class DimPyramidTests(unittest.TestCase):
    """A pyramid leaves only by being broken, and a broken cell reads
    plainly EMPTY. That justified deleting an unseen pyramid track on the
    spot - while a pyramid read 0.88-0.99. Since the walkable highlight
    left the mask a solid one reads about .54 against a .40 threshold,
    and a marginal pyramid - half scrolled off the left edge - dips under
    the line for a frame.

    Measured over 509 obstacles that stopped being obstacles with no
    scroll and no attack: the next frame reads below .15 in 454 of them
    and the pyramid comes back in 2%, while in the .25-.40 band it comes
    back in 45%. Dim is a track the eyes lost, not a cell that was
    cleared.

    Run 20260830T001653 frame 0068 is what the old rule cost: (2,0) read
    .51/.55/.51/.57 and then .3957 - five thousandths under the line. The
    track was deleted, the planner routed THROUGH the cell, and the move
    tap executed a hidden 200-shard garra."""

    def test_a_dim_cell_keeps_its_pyramid(self):
        world = running()
        world.observe(seen(pyramids={(2, 0)}), shift=0)
        self.assertIn((2, 0), world.believed_pyramids())
        world.observe(seen(), shift=0, dim={(2, 0)})
        self.assertIn((2, 0), world.believed_pyramids())

    def test_a_plainly_empty_cell_still_drops_it_at_once(self):
        world = running()
        world.observe(seen(pyramids={(2, 0)}), shift=0)
        world.observe(seen(), shift=0)
        self.assertNotIn((2, 0), world.believed_pyramids())

    def test_a_dim_cell_does_not_confirm_anything_either(self):
        """Blind, not seen: a dim frame must not feed a track evidence,
        or a flicker would keep a dead pyramid alive forever."""
        world = running()
        world.observe(seen(pyramids={(2, 0)}), shift=0)
        before = world.at((2, 0)).sightings
        world.observe(seen(), shift=0, dim={(2, 0)})
        self.assertEqual(world.at((2, 0)).sightings, before)


class CollectionTests(unittest.TestCase):
    """Standing on a cell collects it: the track ends there, with no
    separate memory-pop, phantom-drop and contradiction rule."""

    def test_standing_on_a_track_ends_it(self):
        world = running()
        world.observe(seen(items={(2, 4): "orange"}), shift=1)
        world.observe(seen(items={(2, 3): "orange"}), shift=1)
        world.observe(seen(), shift=1, player=(2, 2))
        self.assertIsNone(world.at((2, 2)))

    def test_a_pyramid_under_the_player_is_impossible(self):
        # Standing proves the cell is walkable: a pyramid track there
        # is a misread and dies on the spot.
        world = running()
        world.observe(seen(pyramids={(2, 2)}), shift=0)
        world.observe(seen(), shift=0, player=(2, 2))
        self.assertIsNone(world.at((2, 2)))


class IncomingPipelineTests(unittest.TestCase):
    """What is being built from the right, kept in memory through its
    stages - the planning surface the user asked for. The preview says
    a pyramid is coming; the board says how much of the run has landed;
    together they say whether a wall is worth positioning for BEFORE it
    arrives."""

    def test_preview_predicts_and_the_board_confirms(self):
        world = wm.WorldModel()
        preview = [False, False, False, True, False]
        world.observe(seen(), shift=0, preview=preview)
        self.assertEqual(world.predicted_rows(), {3})
        # It lands at the right edge on the next scroll.
        world.observe(seen(pyramids={(3, 4)}), shift=1, preview=preview)
        self.assertEqual(world.at((3, 4)).origin, "right_edge")
        self.assertTrue(world.prediction_confirmed(3))

    def test_incoming_wall_counts_landed_plus_promised(self):
        # Built the only way the game builds one: a pyramid enters at
        # the edge, the next scroll carries it left and the next one
        # lands behind it.
        world = running()
        preview = [False, False, False, True, False]
        world.observe(seen(pyramids={(3, 4)}), shift=1, preview=preview)
        world.observe(seen(pyramids={(3, 3), (3, 4)}), shift=1,
                      preview=preview)
        wall = world.incoming_wall(3)
        self.assertEqual(wall.landed, 2)
        self.assertEqual(wall.promised, 1)
        self.assertTrue(wall.dashable)

    def test_a_lone_promise_is_not_a_wall(self):
        world = wm.WorldModel()
        world.observe(seen(), shift=0,
                      preview=[False, False, False, True, False])
        self.assertFalse(world.incoming_wall(3).dashable)

    def test_a_forming_run_that_would_be_scrolled_away_is_flagged(self):
        # Run 20260822T234822 n=14, replayed as it happened: two
        # pyramids rode in and drifted to columns 1-2 while a third
        # landed at the edge. Every further scroll now eats one of the
        # bot's own pyramids - the shape it must stop scrolling and
        # dash instead.
        preview = [False, False, False, False, True]
        world = running()
        world.observe(seen(pyramids={(4, 4)}), shift=1, preview=preview)
        world.observe(seen(pyramids={(4, 3), (4, 4)}), shift=1,
                      preview=preview)
        world.observe(seen(pyramids={(4, 2), (4, 3)}), shift=1,
                      preview=preview)
        world.observe(seen(pyramids={(4, 1), (4, 2), (4, 4)}), shift=1,
                      preview=preview)
        wall = world.incoming_wall(4)
        self.assertEqual(wall.landed, 2)
        self.assertEqual(wall.launch, (4, 0))
        self.assertTrue(wall.erodes_on_scroll)


class NoReprocessingTests(unittest.TestCase):
    """One pass per frame over the detections. The old stack ran six
    set-algebra stages over every cell every frame and still disagreed
    with itself; the model updates each track once."""

    def test_observe_touches_each_detection_once(self):
        world = running()
        world.observe(seen(items={(1, 4): "orange"}), shift=1)
        before = world.stats()["updates"]
        world.observe(seen(items={(1, 3): "orange", (2, 4): "claw"}),
                      shift=1)
        after = world.stats()["updates"]
        self.assertEqual(after - before, 2)

    def test_beliefs_are_read_without_recomputation(self):
        world = running()
        world.observe(seen(items={(1, 4): "orange"}), shift=1)
        touched = world.stats()["updates"]
        world.believed_items()
        world.suspect_cells()
        world.believed_items()
        self.assertEqual(world.stats()["updates"], touched)



class DashConfettiTests(unittest.TestCase):
    """A dash's own animation must not be believed as loot.

    The right-edge amnesty says a thing inside the last `shift` columns
    arrived through the edge, so it is believed on sight. A dash breaks
    that bet twice over: it scrolls three columns, which widens the band
    to columns 2-4, and it throws a pickup animation across exactly
    those columns.

    Measured over the recordings: one frame after a dash the board shows
    2.37 items against a 1.63 baseline and 18% of those frames carry
    five or more (n=346); by the second frame it is 1.67 and 8%, which is
    the baseline. The confetti lives one frame, inside the band.

    Run 20260828T172224 n=68-71 (user report): dash, seven oranges, one
    of them remembered at (1,1), a paw up to fetch it, energy unchanged
    at 11270, a paw back down.
    """

    def test_the_edge_amnesty_believes_on_sight_after_a_normal_scroll(self):
        model = wm.WorldModel()
        model.observe({"items": {}, "pyramids": set()})
        model.observe({"items": {(1, 4): "orange"}, "pyramids": set()}, shift=1)
        self.assertIn((1, 4), model.believed_items())

    def test_a_dash_frame_believes_nothing_on_sight(self):
        model = wm.WorldModel()
        model.observe({"items": {}, "pyramids": set()})
        model.observe({"items": {(1, 2): "orange", (1, 3): "orange",
                                 (1, 4): "orange"}, "pyramids": set()},
                      shift=3, edge_explains=False)
        self.assertEqual(model.believed_items(), {})
        self.assertEqual(model.suspect_cells(),
                         {(1, 2), (1, 3), (1, 4)})

    def test_a_real_item_is_believed_once_the_doubt_is_paid(self):
        # The price of the doubt: an unexplained birth waits
        # CONFIRM_SIGHTINGS sightings. The confetti beside it never
        # reaches the second one.
        model = wm.WorldModel()
        model.observe({"items": {}, "pyramids": set()})
        model.observe({"items": {(1, 3): "orange", (1, 4): "orange"},
                       "pyramids": set()}, shift=3, edge_explains=False)
        for _ in range(wm.CONFIRM_SIGHTINGS - 2):
            model.observe({"items": {(1, 3): "orange"}, "pyramids": set()})
            self.assertEqual(model.believed_items(), {}, "todavia en duda")
        model.observe({"items": {(1, 3): "orange"}, "pyramids": set()})
        self.assertIn((1, 3), model.believed_items())
        self.assertNotIn((1, 4), model.believed_items())


class UnbilledScrollTests(unittest.TestCase):
    """A tracked entity cannot disappear and cannot be reborn.

    The receipt is the belt's authority and it can UNDER-count: a paw
    reading the HUD could not resolve leaves conveyor_shift a column
    short. The world moved anyway, so every track sits one column right
    of what the eyes report - and the eyes are right.

    Run 20260828T213035 obs#48-49 (user: "no pudieron desaparecer ni
    haber aparecido... si las habia visto antes, ya sabe que estan ahi,
    pero despues no las coge"): two steps cards tracked at (2,4) and
    (4,3) with six sightings; the next frame the eyes put them at (2,3)
    and (4,2) with shift 0. The tracks aged out on misses while the
    sightings started fresh, unexplained, suspect tracks one column
    left, and the bot walked past cards it had watched for six frames.
    """

    def watched(self, cells, pyramids=frozenset(), frames=6):
        model = wm.WorldModel()
        for _ in range(frames):
            model.observe({"items": {cell: "steps" for cell in cells},
                           "pyramids": set(pyramids)})
        return model

    def test_the_tracks_follow_the_eyes(self):
        model = self.watched(((2, 4), (4, 3)))
        model.observe({"items": {(2, 3): "steps", (4, 2): "steps"},
                       "pyramids": set()})
        self.assertEqual(model.believed_items(),
                         {(2, 3): "steps", (4, 2): "steps"})
        self.assertEqual(model.suspect_cells(), set())

    def test_a_stale_pyramid_does_not_block_it(self):
        # The first version of this rule demanded the left cell be empty
        # of ANY track, and there was a stale pyramid track exactly where
        # the cards had slid to - so it never fired on the case it was
        # written for.
        model = self.watched(((2, 4), (4, 3)), pyramids={(2, 3), (4, 2)})
        model.observe({"items": {(2, 3): "steps", (4, 2): "steps"},
                       "pyramids": set()})
        self.assertEqual(model.believed_items(),
                         {(2, 3): "steps", (4, 2): "steps"})

    def test_one_track_sliding_alone_is_not_a_belt(self):
        """Run 20260828T223602 n=65 (user: "dio un paso para atras sin
        razon").

        The bot ate the orange at (3,3); by then the belt had carried
        its track to (3,1), and the pickup burst painted a card on
        (3,0) behind it. With no second witness that is a coincidence,
        not a scroll - and believing it handed a dead orange's six
        sightings to a confetti flake, which the free-grab rule then
        walked backwards to collect.
        """
        model = wm.WorldModel()
        for _ in range(6):
            model.observe({"items": {(3, 1): "orange"}, "pyramids": set()})
        model.observe({"items": {(3, 0): "orange"}, "pyramids": set()})
        self.assertIn((3, 0), model.suspect_cells())
        self.assertNotIn((3, 0), model.believed_items())

    def test_a_pyramid_can_be_the_second_witness(self):
        # The belt carries pyramids too, so one card plus one pyramid
        # moving by the same column is a scroll like any other.
        model = wm.WorldModel()
        for _ in range(6):
            model.observe({"items": {(2, 4): "steps"},
                           "pyramids": {(4, 3)}})
        model.observe({"items": {(2, 3): "steps"}, "pyramids": {(4, 2)}})
        self.assertEqual(model.believed_items(), {(2, 3): "steps"})

    def test_two_real_neighbours_are_never_merged(self):
        # The rival claim the guard is for. This is the case that killed
        # the version reverted earlier the same day: it handed the
        # history to whatever twin sat there, so collecting the left one
        # merged two real cards (replay corpus, 20260823T142253 n=32).
        model = wm.WorldModel()
        for _ in range(6):
            model.observe({"items": {(2, 3): "steps", (2, 4): "steps"},
                           "pyramids": set()})
        model.observe({"items": {(2, 3): "steps"}, "pyramids": set()})
        self.assertEqual(model.believed_items(),
                         {(2, 3): "steps", (2, 4): "steps"})

    def test_a_different_category_is_a_different_thing(self):
        model = self.watched(((2, 4), (4, 3)))
        model.observe({"items": {(2, 3): "orange", (4, 2): "steps"},
                       "pyramids": set()})
        self.assertIn((2, 4), model.believed_items())
        self.assertIn((2, 3), model.suspect_cells())

    def test_it_only_looks_one_column_left(self):
        model = self.watched(((2, 4), (4, 3)))
        model.observe({"items": {(2, 2): "steps", (4, 2): "steps"},
                       "pyramids": set()})
        self.assertIn((2, 4), model.believed_items())
        self.assertIn((2, 2), model.suspect_cells())


class RefutedPyramidTests(unittest.TestCase):
    """A believed pyramid the eyes deny at the moment of the swing.

    Pyramids are believed unconditionally - doubting the strongest
    signal on the board only ever walked the bot into one - which also
    means a misdetected pyramid track is immortal. Run
    20260823T145105 minted one at (0,2), merged it as an obstacle every
    frame, planned a garra at it every frame, and the runner refused the
    garra every frame because raw vision saw an empty cell: 579 frames,
    zero actions, the run never ended.

    The refusal is the adjudication. Raw pixels at the instant of the
    swing outrank a track built from earlier frames, so the track dies.
    """

    def test_a_refuted_pyramid_stops_being_believed(self):
        world = wm.WorldModel()
        world.observe(seen(pyramids=[(0, 2)]))
        self.assertIn((0, 2), world.believed_pyramids())
        world.refute((0, 2))
        self.assertNotIn((0, 2), world.believed_pyramids())

    def test_refuting_an_untracked_cell_is_harmless(self):
        world = wm.WorldModel()
        world.observe(seen(pyramids=[(0, 2)]))
        world.refute((4, 4))
        self.assertIn((0, 2), world.believed_pyramids())

    def test_a_refuted_cell_can_be_seen_again_later(self):
        # The eyes are the authority in both directions: a real pyramid
        # that was momentarily invisible must be able to come back.
        world = wm.WorldModel()
        world.observe(seen(pyramids=[(0, 2)]))
        world.refute((0, 2))
        world.observe(seen(pyramids=[(0, 2)]))
        self.assertIn((0, 2), world.believed_pyramids())

    def test_refuting_does_not_disturb_a_neighbouring_item(self):
        world = wm.WorldModel()
        world.observe(seen(items=[((0, 3), "orange")], pyramids=[(0, 2)]))
        world.refute((0, 2))
        self.assertIn((0, 3), world.believed_items())


if __name__ == "__main__":
    unittest.main()
