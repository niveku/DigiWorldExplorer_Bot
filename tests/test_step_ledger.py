"""The pink paw counter is the game telling us what it actually did.

The board is a fixed grid. Its CONTENTS ride a conveyor belt that advances
exactly one column left when a charged step carries the player from column 1
into column 2 - and never for any other reason. So "did my tap land?" is not
a vision question: the game charges a paw, or it does not.
"""
import unittest

import step_ledger as ledger


class ChargedStepsTests(unittest.TestCase):
    def test_a_charged_step_spends_exactly_one_paw(self):
        self.assertEqual(ledger.charged_steps(3649, 3648, taps=1), 1)

    def test_a_swallowed_tap_spends_nothing(self):
        self.assertEqual(ledger.charged_steps(3649, 3649, taps=1), 0)

    def test_a_batch_reports_how_many_of_its_taps_the_game_took(self):
        # Run 20260823T074036 #8: two taps sent, one paw spent, and the
        # player landed on the FIRST target - the game froze mid-batch.
        self.assertEqual(ledger.charged_steps(3641, 3640, taps=2), 1)

    def test_a_steps_card_pays_five_paws_back(self):
        # Same run #10 and #55: one step onto a card, counter +4 net. The
        # caller does not have to know a card landed - with batches of at
        # most three taps, exactly one card count fits the arithmetic.
        self.assertEqual(ledger.charged_steps(3640, 3644, taps=1), 1)

    def test_a_reading_two_card_bonuses_could_explain_is_refused(self):
        # Only a batch far larger than the runner ever sends could make
        # two answers fit; if one ever does, the ledger must not guess.
        self.assertIsNone(ledger.charged_steps(100, 100, taps=8))

    def test_an_unreadable_counter_answers_none_not_zero(self):
        self.assertIsNone(ledger.charged_steps(None, 3648, taps=1))
        self.assertIsNone(ledger.charged_steps(3649, None, taps=1))

    def test_a_misread_digit_is_refused_instead_of_believed(self):
        # Same run #11: the reader saw "3" where the HUD said 3642. A
        # frame cannot spend thousands of paws, so the ledger declines.
        self.assertIsNone(ledger.charged_steps(3644, 3, taps=1))
        self.assertIsNone(ledger.charged_steps(3, 3642, taps=1))

    def test_spending_more_paws_than_taps_sent_is_refused(self):
        self.assertIsNone(ledger.charged_steps(3649, 3646, taps=1))

    def test_a_frame_that_sent_no_move_tap_charges_nothing(self):
        self.assertEqual(ledger.charged_steps(3649, 3649, taps=0), 0)


class SaneReadingTests(unittest.TestCase):
    """A misread digit must not poison the ledger for a second frame."""

    def test_an_ordinary_step_is_believed(self):
        self.assertEqual(ledger.sane_reading(3649, 3648, taps=1), 3648)

    def test_a_card_refund_is_believed(self):
        self.assertEqual(ledger.sane_reading(3640, 3644, taps=1), 3644)

    def test_a_thousand_paw_jump_is_a_misread_not_a_frame(self):
        # Run 20260823T074036 #11: the reader saw "3" for 3642. Refusing
        # the READING (not just the arithmetic) keeps the previous count
        # as the reference, so only one frame falls back.
        self.assertIsNone(ledger.sane_reading(3644, 3, taps=1))

    def test_the_first_reading_of_a_run_has_nothing_to_contradict_it(self):
        self.assertEqual(ledger.sane_reading(None, 3649, taps=0), 3649)

    def test_an_unreadable_counter_stays_unreadable(self):
        self.assertIsNone(ledger.sane_reading(3649, None, taps=1))


class ConveyorLawTests(unittest.TestCase):
    """Only a charged right step INTO screen column >= 2 slides the world."""

    def test_a_right_step_into_column_two_advances_the_belt(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=1), 1)

    def test_a_right_step_into_column_one_does_not(self):
        sent = [{"type": "move", "target_cell": [2, 1], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=1), 0)

    def test_vertical_and_left_steps_never_move_the_world(self):
        for direction, cell in (("up", [1, 2]), ("down", [3, 2]),
                                ("left", [2, 0])):
            sent = [{"type": "move", "target_cell": cell,
                     "direction": direction}]
            self.assertEqual(ledger.conveyor_shift(sent, charged=1), 0,
                             f"{direction} moved the belt")

    def test_an_uncharged_tap_moves_nothing(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=0), 0)

    def test_only_the_taps_the_game_took_count_and_they_are_the_first(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"},
                {"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=2), 2)
        self.assertEqual(ledger.conveyor_shift(sent, charged=1), 1)

    def test_attacks_are_not_steps_and_never_slide_the_world(self):
        sent = [{"type": "attack", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=0), 0)

    def test_the_charge_budget_skips_over_non_move_taps(self):
        # An attack spends no paw, so a charge of 1 belongs to the move
        # that follows it, not to the attack.
        sent = [{"type": "attack", "target_cell": [2, 1], "direction": "right"},
                {"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.conveyor_shift(sent, charged=1), 1)


class RefusedTapTests(unittest.TestCase):
    """The game charging nothing IS the refusal - no vision needed.

    The old detector inferred a refusal from the player still standing on
    the pre-move cell, and admitted in its own docstring that it could
    not judge a scroll ride (which lands on the same screen cell by
    design). The receipt has no such blind spot.
    """

    def test_a_fully_charged_batch_refuses_nothing(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertIsNone(ledger.refused_tap(sent, charged=1))

    def test_the_first_uncharged_move_is_the_one_the_game_refused(self):
        sent = [{"type": "move", "target_cell": [1, 1], "direction": "up"},
                {"type": "move", "target_cell": [0, 1], "direction": "up"}]
        self.assertEqual(ledger.refused_tap(sent, charged=1), (0, 1))

    def test_a_scroll_ride_refusal_is_visible_too(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.refused_tap(sent, charged=0), (2, 2))

    def test_an_unanswered_ledger_accuses_nobody(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertIsNone(ledger.refused_tap(sent, charged=None))

    def test_attacks_are_never_accused_of_being_refused(self):
        sent = [{"type": "attack", "target_cell": [2, 2], "direction": "right"}]
        self.assertIsNone(ledger.refused_tap(sent, charged=0))


class MoveTapCountTests(unittest.TestCase):
    def test_it_counts_only_the_taps_that_cost_a_paw(self):
        sent = [{"type": "attack", "target_cell": [2, 2]},
                {"type": "move", "target_cell": [2, 2]},
                {"type": "dash", "target_cell": [2, 4]},
                {"type": "move", "target_cell": [2, 2]}]
        self.assertEqual(ledger.move_taps(sent), 2)


class ChargeFromPixelsTests(unittest.TestCase):
    """When the receipt is unreadable, the pixel sensor fills the same slot.

    One quantity - how many taps the game took - with a strict order of
    authority behind it: the receipt, then the pixels, then the taps we
    sent. Never two mechanisms arguing.
    """

    def test_a_measured_column_names_the_tap_that_moved_it(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"},
                {"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.charge_matching_shift(sent, 1), 1)
        self.assertEqual(ledger.charge_matching_shift(sent, 2), 2)

    def test_a_still_world_means_no_scroll_tap_was_taken(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.charge_matching_shift(sent, 0), 0)

    def test_more_columns_than_taps_could_move_is_refused(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertIsNone(ledger.charge_matching_shift(sent, 2))

    def test_an_unmeasured_world_answers_nothing(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertIsNone(ledger.charge_matching_shift(sent, None))

    def test_a_still_world_cannot_tell_vertical_taps_apart(self):
        # Vertical steps never move the belt, so zero columns is equally
        # true whether the game took them or not: the pixels must not be
        # read as proof that nothing happened.
        sent = [{"type": "move", "target_cell": [3, 1], "direction": "down"}]
        self.assertIsNone(ledger.charge_matching_shift(sent, 0))


class LandingTests(unittest.TestCase):
    """Where the player stands once the game took `charged` of the taps."""

    def test_a_charged_scroll_step_leaves_the_player_back_in_column_one(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.landing(sent, charged=1, player=(2, 1)),
                         (2, 1))

    def test_an_uncharged_tap_leaves_the_player_where_it_stood(self):
        sent = [{"type": "move", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.landing(sent, charged=0, player=(2, 1)),
                         (2, 1))

    def test_a_vertical_step_simply_lands_on_its_target(self):
        sent = [{"type": "move", "target_cell": [3, 1], "direction": "down"}]
        self.assertEqual(ledger.landing(sent, charged=1, player=(2, 1)),
                         (3, 1))

    def test_a_half_taken_batch_lands_on_the_last_charged_tap(self):
        sent = [{"type": "move", "target_cell": [1, 1], "direction": "up"},
                {"type": "move", "target_cell": [0, 1], "direction": "up"}]
        self.assertEqual(ledger.landing(sent, charged=1, player=(2, 1)),
                         (1, 1))

    def test_an_attack_does_not_move_the_player(self):
        sent = [{"type": "attack", "target_cell": [2, 2], "direction": "right"}]
        self.assertEqual(ledger.landing(sent, charged=0, player=(2, 1)),
                         (2, 1))


if __name__ == "__main__":
    unittest.main()
