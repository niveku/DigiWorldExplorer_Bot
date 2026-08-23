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
        world = running()
        world.observe(seen(items={(3, 1): "orange"}), shift=0)
        world.observe(seen(items={(3, 1): "orange"}), shift=0)
        self.assertEqual(world.at((3, 1)).origin, "unexplained")
        self.assertNotIn((3, 1), world.believed_items())

    def test_confetti_that_outlives_two_frames_is_believed(self):
        world = running()
        for _ in range(3):
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
        world = running()
        world.observe(seen(items={(3, 1): "orange"}), shift=0)
        world.observe(seen(), shift=0)                    # gone
        world.observe(seen(items={(3, 1): "orange"}), shift=0)
        self.assertNotIn((3, 1), world.believed_items())


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


if __name__ == "__main__":
    unittest.main()
