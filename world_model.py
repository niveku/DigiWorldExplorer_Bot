"""Tracked world model: what exists, where it came from, what is coming.

Replaces the six-mechanism suspicion stack (fresh appearances, two-frame
carryover, burst holds, sticky left-band holds, remembered-suspect drops
and clean-miss decay) that grew one rule per field bug during
2026-08-22 and ended up disagreeing with itself - see
docs/review-2026-08-22.md for the audit that motivated this.

The idea it replaces them with: an entity on the board is a TRACK with
an identity, not a cell that gets re-judged every frame.

  - Identity survives the scroll. The pixel sensor measures how far the
    world moved, so last frame's track at (r, c) is this frame's track
    at (r, c - shift). Every stage of the old stack had to remember to
    compensate for this and half of them forgot.

  - Identity survives being covered. Confetti painting over a real item
    for a frame used to make its reappearance look like a brand-new
    arrival, restarting every clock. A track that is not seen simply
    misses a frame.

  - Origin is decided ONCE, at birth, from physics: items and pyramids
    enter only at the right edge as the world scrolls, or where a garra
    just broke a pyramid. A birth that neither explains is animation
    residue, and residue cannot outlive two settled frames.

  - Suspicion is one property of a track (unexplained origin, not yet
    confirmed), so there is exactly one place where it can be wrong.

  - What the sixth-column preview promises is kept as a PREDICTION and
    confirmed when it lands, so the planner can position for a wall
    while it is still arriving instead of reacting after it is whole.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BOARD = 5
# Confetti lives on the pickup frame and the one after it (measured
# across the 2026-08-20/22 runs), so a third settled sighting means the
# thing is real no matter how it was born.
#
# Re-priced to 2 on 2026-08-29, once `observe` learned to refuse confetti
# by its CAUSE and this statistical stand-in could be measured against
# it. Ground truth: the game's own energy counter over 916 recorded steps
# onto a cell the board showed as an orange, 45 runs, split BY RUN.
# Waiting three frames was never confetti-specific - it delayed every
# real pickup equally, and a real pickup is worth +125 against the ~18 a
# wasted paw costs. Two keeps a floor under detector flicker without
# making the bot late for everything.
CONFIRM_SIGHTINGS = 2
# A track survives this many consecutive unseen frames. Confetti cover
# and detection flicker last one; three is the same tolerance the old
# clean-miss decay converged on.
MAX_MISSES = 3


@dataclass
class Track:
    """One entity on the board, followed across frames."""
    cell: tuple
    kind: str                 # "item" | "pyramid"
    category: str | None      # orange, claw, steps, dash_orb, tickets
    origin: str               # initial | right_edge | reveal | unexplained
    born: int
    sightings: int = 1
    misses: int = 0

    @property
    def explained(self):
        return self.origin != "unexplained"

    @property
    def believed(self):
        """Real enough to act on.

        An explained birth is believed at once - it is where the game
        puts things. An unexplained one has to outlive the confetti.
        Pyramids are always believed: the confetti phenomenon paints
        CARDS, never pyramids, and a pyramid reads 0.88-0.99 against
        an item's 0.06-0.20 - doubting the strongest signal on the
        board only ever walked the bot into one."""
        return (self.kind == "pyramid" or self.explained
                or self.sightings >= CONFIRM_SIGHTINGS)

    @property
    def stage(self):
        if self.believed:
            return "confirmed"
        return "provisional" if self.sightings > 1 else "new"


@dataclass
class IncomingWall:
    """A run of pyramids arriving in one row: what has landed, what the
    preview still promises, and whether the bot should act now."""
    row: int
    landed: int = 0
    promised: int = 0
    launch: tuple | None = None
    erodes_on_scroll: bool = False

    @property
    def total(self):
        return self.landed + self.promised

    @property
    def dashable(self):
        # A dash breaks the three cells ahead of the launch, so two
        # landed pyramids are the floor: one landed plus a promise is a
        # bet on a preview, and previews flicker.
        return self.landed >= 2 and self.total >= 2


class WorldModel:
    def __init__(self):
        self.tracks: dict[tuple, Track] = {}
        self.frame = 0
        self.preview = [False] * BOARD
        self._confetti: set = set()   # this frame's refused confetti
        self._predicted: dict[int, int] = {}   # row -> frame first promised
        self._confirmed: set[int] = set()
        self._updates = 0

    # ---- observation -------------------------------------------------

    def observe(self, detections, shift=0, player=None, revealed=(),
                preview=None, occluded=(), edge_explains=True,
                collected=False):
        """Fold one frame of vision into the model.

        `detections` is {"items": {cell: category}, "pyramids": {cells}}
        in THIS frame's coordinates; `shift` is the measured scroll
        since the previous observation. One pass, one update per
        detection - nothing is recomputed from scratch."""
        self.frame += 1
        first_frame = self.frame == 1
        self._advance(shift)
        if preview is not None:
            self._absorb_preview(preview)

        items = dict(detections.get("items") or {})
        pyramids = set(detections.get("pyramids") or ())
        revealed = {tuple(cell) for cell in revealed}
        # CONFETTI, stated as the game states it (user law 2026-08-29):
        # it exists only where something was just collected - a step
        # onto a pickup, or a dash, which sweeps everything in its lane.
        # Nowhere else, ever. And it is only ever NOISE ADDED: it paints
        # new cards over the board, it does not remove what is there.
        #
        # So the answer is not "how crowded is the frame" - a board CAN
        # hold five real drops at once, and counting them punished
        # exactly the frames worth having (run 20260829T234223 n=421:
        # four real pickups, energy flat for three frames, all four
        # refused). The answer is: on a frame that collected something,
        # refuse the sightings that are NEW where nothing can legally be
        # born - and touch nothing else.
        #
        # Measured against the game's own energy counter, 916 recorded
        # steps onto a cell the board showed as an orange:
        #
        #     >=4 items, nothing collected in 3 frames :   4 real,   0 fake
        #     >=4 items, collected on the last frame   :  60 real, 240 fake
        #     <=3 items, nothing collected in 3 frames :  31 real,   1 fake
        #     <=3 items, collected on the last frame   : 541 real,  36 fake
        #
        # A crowded board with no collection behind it was real every
        # single time. The cause separates them; the crowd does not.
        #
        # What this deliberately does NOT do is forget. A track already
        # believed stays believed and stays a target straight through
        # the burst - the bot goes and gets what it already knows is
        # there, because confetti cannot make a real pickup vanish.
        confetti = set()
        if collected:
            for cell in list(items):
                if (cell in self.tracks or cell in revealed
                        or first_frame or self._edge_born(cell, shift)):
                    continue
                confetti.add(cell)
                del items[cell]
        self._confetti = confetti
        seen_cells = set(items) | pyramids

        # ---- the belt moved and the ledger did not count it ------
        # The receipt is the belt's authority, and it can UNDER-count: a
        # paw reading the HUD could not resolve leaves conveyor_shift one
        # column short. The world moved anyway, so from that frame on
        # every track sits one column right of what the eyes report - and
        # the eyes are right, because a tracked entity cannot teleport
        # and cannot be born where one already stands.
        #
        # Run 20260828T213035 obs#48-52 (user: "no pudieron desaparecer
        # ni haber aparecido... si las habia visto antes, ya sabe que
        # estan ahi, pero despues no las coge"): two steps cards tracked
        # at (2,4) and (4,3) with six sightings; the next frame the eyes
        # put them at (2,3) and (4,2) with shift 0. The tracks aged out
        # on misses while the sightings started fresh tracks one column
        # left - unexplained, one sighting, suspect - and the bot walked
        # past cards it had been watching for six frames.
        #
        # So: an unseen track whose own category IS seen exactly one
        # column to its left, on a cell no other track claims, is that
        # same entity after a scroll nobody billed. Move it; do not
        # duplicate it. This runs BEFORE the sighting loop, so the moved
        # track collects the sighting and no fresh one is born beside it.
        #
        # The "no other track claims it" guard is the whole difference
        # from the version reverted earlier today, which handed the
        # history to whatever twin sat there and so merged two real
        # neighbours the moment the left one was collected (caught by the
        # replay corpus on 20260823T142253 n=32).
        #
        # And the belt moves EVERYTHING. One track sliding a column on
        # its own is not a scroll, it is a coincidence - which is how a
        # collected orange handed its history to a confetti flake in run
        # 20260828T223602 n=65 (user: "dio un paso para atras sin
        # razon... si ya habia pasado por esa celda y no habia nada, por
        # que ahora si habria de haber algo?"). The orange the bot had
        # just eaten at (3,3) had shifted to (3,1); the pickup burst
        # painted a card at (3,0); the rule moved the dead track onto it
        # and the flake was believed on sight. So a re-sync needs a
        # SECOND track agreeing on the same one-column offset. Two cards
        # moved together in the run this was written for; the flake had
        # nobody. Pyramids count as witnesses - the belt carries them
        # too - and the cost of holding back on a lone candidate is only
        # that a real item spends three frames re-confirming.
        slid = []
        for cell, track in sorted(self.tracks.items()):
            if cell in seen_cells or track.kind != "item":
                continue
            left = (cell[0], cell[1] - 1)
            if left[1] < 0 or left not in items:
                continue
            # Blocked only by another ITEM track: that is the rival claim
            # the guard is for. A PYRAMID track sitting there is stale by
            # the same drift - the eyes are calling that cell a pickup
            # this very frame - and the miss loop below would delete it
            # anyway, since a pyramid vision reports as gone is gone.
            # Requiring the cell to be empty of ANY track is what stopped
            # this firing on the case it was written for: run
            # 20260828T213035 obs#49 had a stale pyramid track at (2,3)
            # and (4,2), exactly where the two cards had slid to.
            rival = self.tracks.get(left)
            if rival is not None and rival.kind == "item":
                continue
            if items[left] != track.category:
                continue
            slid.append((cell, left, track))
        witnesses = len(slid) + sum(
            1 for cell, track in self.tracks.items()
            if track.kind == "pyramid" and cell not in seen_cells
            and (cell[0], cell[1] - 1) in pyramids)
        if witnesses >= 2:
            for cell, left, track in slid:
                track.cell = left
                track.misses = 0
                self.tracks[left] = self.tracks.pop(cell)


        for cell in seen_cells:
            kind = "pyramid" if cell in pyramids else "item"
            category = None if kind == "pyramid" else items.get(cell)
            self._update(cell, kind, category, shift, first_frame, revealed,
                         edge_explains)

        # Cells the partner's own body covers are UNOBSERVABLE, not
        # empty: their colours are wiped precisely because they read as
        # false pickups, so a track under the sprite must neither age
        # nor gain confidence.
        blind = {tuple(cell) for cell in occluded} | confetti
        for cell, track in list(self.tracks.items()):
            if cell in blind:
                continue
            covered = (track.kind == "pyramid" and cell in items
                       and cell not in pyramids)
            if cell in seen_cells and not covered:
                continue
            if covered:
                # A pickup reading on a pyramid's cell is confetti, and
                # the pyramid outlives the card painted over it (run
                # 20260822T160202 n=89). But only for as long as
                # confetti lasts: measured over 709 quiet frame pairs,
                # 87.8% of interior pickup sightings are gone by the
                # next frame and 95.4% within two. An item still there
                # on the third frame is an ITEM, and the pyramid that
                # was on that cell is gone.
                #
                # Without this the track was immortal: being "seen" as
                # an item kept it out of the decay loop below, so it
                # never aged. Run 20260829T201007: the pyramid at (1,4)
                # left the screen at n=73, an orange took the cell, and
                # the dead track rode the belt left for four frames -
                # (1,4) -> (1,3) -> (1,2) - until `covered_pyramids`
                # stamped pyramid=.9 over a REAL orange at (1,2) one
                # step from the bot. The planner walked away from it and
                # spent four paws coming back (user: "no recogio una
                # energia, es como si se hubiera descachado").
                track.misses += 1
                if track.misses >= MAX_MISSES:
                    # Hand the cell to the item that was there all
                    # along. Deleting the track instead would make the
                    # pickup a newborn - unexplained, and three more
                    # sightings before it can be acted on - for
                    # something the screen has been showing since the
                    # cover began. It cannot have arrived here: nothing
                    # is born in the interior (user law 2026-08-29).
                    track.kind = "item"
                    track.category = items[cell]
                    track.sightings = track.misses
                    track.misses = 0
                continue
            track.misses += 1
            # A pyramid that vision reports as plainly empty was broken:
            # it does not flicker at 0.88-0.99, and the only other way
            # out is the left edge, which the shift already handles.
            # Items get three frames of tolerance because confetti
            # covers them and the sprite hides them.
            if track.kind == "pyramid" or track.misses >= MAX_MISSES:
                del self.tracks[cell]

        if player is not None:
            # Standing on a cell collects whatever was there and proves
            # it was walkable, so a pyramid track there was a misread.
            self.tracks.pop(tuple(player), None)

    def _advance(self, shift):
        if not shift:
            return
        moved = {}
        for track in self.tracks.values():
            row, col = track.cell
            col -= shift
            if col < 0:
                continue           # scrolled off the left edge, gone
            track.cell = (row, col)
            moved[track.cell] = track
        self.tracks = moved
        self._predicted = {row: born for row, born in self._predicted.items()}

    def _absorb_preview(self, preview):
        self.preview = list(preview)
        for row, lit in enumerate(preview):
            if lit and row not in self._predicted:
                self._predicted[row] = self.frame
            elif not lit:
                self._predicted.pop(row, None)

    def _update(self, cell, kind, category, shift, first_frame, revealed,
                edge_explains=True):
        self._updates += 1
        track = self.tracks.get(cell)
        if track is not None and track.kind == kind:
            track.sightings += 1
            track.misses = 0
            if category:
                track.category = category
            return
        if (track is not None and track.kind == "pyramid"
                and kind == "item"):
            # A card painted over a pyramid does not turn it into a
            # pickup. A pyramid leaves only by being broken - which
            # reads as a plainly EMPTY cell, since pyramids score
            # 0.88-0.99 and do not flicker - or by scrolling off. Run
            # 20260822T160202 n=89 tapped such a cell and paid a hidden
            # 200-shard garra; suspecting the whole neighbourhood was
            # the old, blunt answer.
            #
            # The cover is NOT a sighting, so the miss counter is left
            # alone for `observe`'s decay pass to raise. Zeroing it here
            # made the track immortal: it was "seen" (as an item), so
            # the decay loop skipped it, and the reset undid the one
            # miss it did accrue. See the covered-track note in
            # `observe` for what that cost in run 20260829T201007.
            return
        origin = self._classify(cell, shift, first_frame, revealed,
                                edge_explains)
        self.tracks[cell] = Track(cell=cell, kind=kind, category=category,
                                  origin=origin, born=self.frame)
        if kind == "pyramid" and origin == "right_edge":
            row = cell[0]
            if row in self._predicted:
                self._confirmed.add(row)

    def _edge_born(self, cell, shift):
        """True where the belt can legally have just delivered this cell.

        The board's only door. After a one-column scroll that is column
        4; after a three-column dash it is columns 2 to 4 - which is
        also why a dash is the one case worth holding a frame for, since
        the far columns are genuinely unknown while the near ones are
        not.
        """
        return bool(shift) and cell[1] >= BOARD - shift

    def _classify(self, cell, shift, first_frame, revealed,
                  edge_explains=True):
        if first_frame:
            return "initial"
        if cell in revealed:
            return "reveal"
        # An entity entering at column 4 on the first of `shift` scrolls
        # ends the interval at column 5 - shift; anything left of that
        # cannot have come in through the edge.
        #
        # Unless the scroll was a DASH. The amnesty is a bet that a thing
        # inside the band arrived through the edge, and a dash is the one
        # move where something else arrives there: its own pickup
        # animation, which throws confetti across the three columns it
        # crossed. Worse, the wider the shift the wider the band - a
        # 3-column dash grants amnesty to columns 2, 3 and 4 at once,
        # which is most of the board. Measured: one frame after a dash
        # the board shows 2.37 items against a 1.63 baseline, and 18% of
        # those frames carry five or more (n=346); by the second frame it
        # is back to 1.67 and 8%. So the confetti lives exactly one frame
        # and lands exactly in the band that believes it on sight. Run
        # 20260828T172224 n=68-71 (user report): dash, seven oranges, one
        # of them remembered at (1,1), a paw up to fetch it, no energy
        # gained, a paw back down.
        #
        # Refusing the amnesty costs a real item TWO frames of doubt:
        # unexplained births need CONFIRM_SIGHTINGS=3 sightings. That is
        # affordable precisely where it applies - the band is columns 2-4,
        # the far side of the board, three scrolls from the erosion edge
        # and several steps from the player either way. A phantom, by
        # contrast, is not there for the second sighting at all.
        if shift and edge_explains and cell[1] >= BOARD - shift:
            return "right_edge"
        return "unexplained"

    # ---- beliefs (pure reads, no recomputation) ----------------------

    def at(self, cell):
        return self.tracks.get(tuple(cell))

    def refute(self, cell):
        """Drop a track the eyes denied at the moment of acting on it.

        Pyramids are believed unconditionally, so a misdetected one is
        otherwise immortal: run 20260823T145105 planned a garra at a
        believed pyramid on (0,2) that raw vision could not see, the
        runner refused the swing, and the pair looped for 579 frames
        without a single action. Raw pixels at the instant of the swing
        outrank a track assembled from earlier frames; if the entity is
        really there, the next frame that sees it starts a new track.
        """
        self.tracks.pop(tuple(cell), None)

    def believed_items(self):
        return {cell: track.category
                for cell, track in self.tracks.items()
                if track.kind == "item" and track.believed}

    def believed_pyramids(self):
        return {cell for cell, track in self.tracks.items()
                if track.kind == "pyramid" and track.believed}

    def suspect_cells(self):
        return ({cell for cell, track in self.tracks.items()
                 if not track.believed} | self._confetti)

    def stages(self):
        """Every track by confirmation stage - the memory surface the
        planner reads to know what is still being confirmed."""
        out = {"new": {}, "provisional": {}, "confirmed": {}}
        for cell, track in self.tracks.items():
            out[track.stage][cell] = track
        return out

    def stats(self):
        return {"tracks": len(self.tracks), "updates": self._updates,
                "frame": self.frame}

    # ---- prediction --------------------------------------------------

    def predicted_rows(self):
        """Rows the sixth column says are about to receive a pyramid."""
        return set(self._predicted)

    def prediction_confirmed(self, row):
        return row in self._confirmed

    def incoming_wall(self, row):
        """The run of pyramids arriving in `row`, landed plus promised.

        The run is read from the RIGHT: pyramids already on the board in
        that row, contiguous back from the edge, are what has landed;
        the preview adds what is still outside. `erodes_on_scroll` marks
        the shape the bot must not scroll away - a run whose left side
        already sits in the launch band, where every further scroll eats
        one of its own pyramids."""
        wall = IncomingWall(row=row)
        wall.promised = 1 if self.preview[row] else 0
        pyramids = {cell for cell in self.believed_pyramids()
                    if cell[0] == row}
        if not pyramids:
            return wall
        cols = sorted(col for _, col in pyramids)
        # Longest contiguous run, and where a dash would launch from.
        best_start, best_len = cols[0], 1
        start, length = cols[0], 1
        for col in cols[1:]:
            if col == start + length:
                length += 1
            else:
                start, length = col, 1
            if length > best_len:
                best_start, best_len = start, length
        wall.landed = best_len
        wall.launch = (row, best_start - 1) if best_start >= 1 else None
        wall.erodes_on_scroll = best_start <= 2 and wall.total >= 2
        return wall

    def incoming_walls(self):
        return {row: self.incoming_wall(row) for row in range(BOARD)}
