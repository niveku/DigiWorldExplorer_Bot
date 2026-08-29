#!/usr/bin/env python3
"""DigiWorld explorer with adaptive two/three-action screenshot batches."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import auto_digiworld as strategy
import digiworld_bot as bot
import overlays
import safe_tap
import step_ledger
import world_model


DIR_DELTA = {"right": (0, 1), "left": (0, -1), "down": (1, 0), "up": (-1, 0)}
VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
# Two consecutive HUD reads may differ by a small legitimate gain while the
# bot keeps moving; anything larger looks like a template misread (5<->8).
ENERGY_READ_TOLERANCE = 40
# Pyramids can drop garra/dash consumables, so an empty inventory may refill
# mid-run: retry a disabled action type after this many completed actions.
REENABLE_ACTIONS = 40
# Three consecutive A-B-A-B detections mean the current goals are unreachable
# or misdetected; ban them for a while (forever on the second offence).
LOOP_STRIKES_TO_BAN = 3
TARGET_BAN_ACTIONS = 25


def loop_guard_tripped(recent_states):
    """Detect pacing: A-B-A-B, stuck-in-place, or longer revisit cycles.

    Period-2 alternation was the first observed loop; run 20260820T022548
    added a period-3 goal-conflict cycle the old check never caught. Any
    state revisited three times within the last twelve is a loop.
    """
    if (len(recent_states) >= 4 and
            recent_states[-4] == recent_states[-2] and
            recent_states[-3] == recent_states[-1]):
        return True
    if not recent_states:
        return False
    return recent_states[-12:].count(recent_states[-1]) >= 3


def explore_bounce(loop_guard, item_goals, previous_reason):
    """A tripped loop guard during goal-less exploration is pure waste.

    Run 20260821T154754 n=770-774 bounced (3,0)<->(4,0) for six moves on
    an empty board before the three-strike counter banned the pocket.
    With no pickups on the board there is nothing a repeat visit could
    ever gain, so the ban fires on the first strike instead."""
    return (loop_guard and not item_goals
            and str(previous_reason or "").startswith("explore"))


def should_hold_for_suspects(reason, item_goals, suspect_items, holds):
    """Hold one frame when every visible pickup is still a suspect.

    Run 20260821T154754 n=902-904: all goals suspect-blocked, so the bot
    explored away, backtracked, and only then confirmed the perishable at
    (0,1) - four moves for information a single 0.4s hold delivers. The
    two-frame rule adjudicates every suspect on the very next frame, so
    one hold is always enough and a second is never allowed."""
    if holds >= 2 or not suspect_items:
        # The combined-suspects carryover keeps a fresh cell suspect for
        # TWO frames; a single hold left the bot exploring away from a
        # real orange right before it confirmed (run 20260821T225908
        # n=43, user-spotted). The hold covers the full window now.
        return False
    if not any(cell[1] >= 3 for cell in suspect_items):
        # Known-world doctrine (user 2026-08-22): left-band suspects
        # are confetti that can never be believed or targeted - there
        # is nothing to wait FOR. Only right-band ingestion doubt
        # (columns 3-4) is worth a frame. Run 20260822T174628 spent 22
        # of 58 frames waiting, mostly on post-pickup confetti.
        return False
    if not str(reason).startswith("explore"):
        return False
    return not (set(item_goals) - set(suspect_items))


def corridor_dash_due(action, last_attack, done, preview, dashes_enabled, ttl=4,
                      suspect_cells=(), player=None, left_band_risk=False):
    """Second garra on the same row with another pyramid incoming: dash.

    Run 20260820T025148 events 84-87 spent two garras (400 shards) plus four
    actions breaking pyramids that scrolled one after another into row 3. A
    dash costs the same 400, breaks up to three, and advances three cells -
    strictly better once the row is a corridor. The sixth-column preview
    provides the 'another one is coming' evidence.

    Two guards added 2026-08-22 (multi-agent review, confirmed):
    - The evidence row is the ATTACK TARGET's row while the override
      fires ('dash', player) along the PLAYER's row. Vertical attacks
      make those differ, so a corridor in the row above could spend
      400 shards dashing an empty lane. The rows must match.
    - Every other dash rule defers to left-band pickups; this was the
      only one that did not, so it deleted real remembered items the
      strategy had just routed to (a col-1 item survives exactly one
      scroll; a dash takes three). BELIEVED pickups only: the left-band
      SUSPECT veto retired 2026-08-23 with the strategy's suspect_risk,
      because holding a wall-clearing dash hostage to probable confetti
      cost six paws of dithering in run 20260823T074036
      (docs/review-2026-08-23.md).
    """
    if not dashes_enabled or action is None or action[0] != "attack":
        return False
    if preview is None or last_attack is None:
        return False
    if left_band_risk:
        return False
    row = action[1][0]
    if player is not None and player[0] != row:
        return False
    return (last_attack[0] == row and done - last_attack[1] <= ttl
            and bool(preview[row]))


# Net burn per executed action. Re-measured 2026-08-28 after a run
# starved on steps with the plan saying it would not (user report).
#
# STEPS, from the per-frame paw counter (the reading the ledger already
# trusts), 10 runs / 3,556 actions: 0.821 on average, 0.854 across the
# two runs on today's code, and 0.910 in the worst single run. The old
# 0.78 was ~9% optimistic, which is a whole pack of 50 on a 600-action
# plan. Rounded UP to 0.85: starving mid-run costs the session, while
# over-reserving costs nothing but a bigger number on screen.
#
# GARRAS and DASHES fell on purpose. Garras were cut by the 2026-08-21
# rules ('garras para nada'); dashes by the 2026-08-28 finding that a
# dash does not collect what it breaks, which retired the bare-pair
# dash. Measured over actions SENT: garras 0.0242 all-time but 0.0127 on
# today's code, dashes 0.0340 all-time and 0.0253 today.
#
# The new rates lean on a thin sample - two runs, 158 actions - so they
# are set above what today measured rather than at it, and the worst-case
# row keeps the older, higher numbers.
BURN_PER_ACTION = {"steps": 0.85, "attacks": 0.020, "dashes": 0.025}
#: The same rates in the single worst recorded run. A run that leans
#: hard on garras burns several times the average, so a single confident
#: number would be a lie: the launcher reports both ends. Steps re-read
#: 2026-08-28 (0.910 in the worst of 10 runs); garras and dashes keep the
#: older, higher figures on purpose, because the policies that lowered
#: them are days old and two runs are not enough to promise a floor.
WORST_BURN_PER_ACTION = {"steps": 0.91, "attacks": 0.080, "dashes": 0.056}
SHOP = {"steps": {"unit": 50, "cost": 2000},   # pack of 50 steps
        "attacks": {"unit": 1, "cost": 200},
        "dashes": {"unit": 1, "cost": 400}}


def purchase_recommendation(planned_actions, inventory, margin=1.15):
    """Recommend what to buy so the planned run does not starve mid-way.

    Needs = measured burn rate x planned actions x a 15% margin; only the
    deficit against the current HUD inventory is recommended. Unreadable
    counters are skipped rather than guessed.
    """
    result = {}
    total = 0
    for name, rate in BURN_PER_ACTION.items():
        have = (inventory or {}).get(name)
        if have is None:
            continue
        need = math.ceil(rate * planned_actions * margin)
        deficit = max(0, need - have)
        shop = SHOP[name]
        units = math.ceil(deficit / shop["unit"]) if deficit else 0
        cost = units * shop["cost"]
        entry = {"need": need, "have": have, "deficit": deficit, "cost": cost}
        if shop["unit"] > 1:
            entry["packs"] = units
        result[name] = entry
        total += cost
    result["total_shards"] = total
    return result


def affordable_actions(inventory):
    """How far the current inventory reaches, and what runs out first.

    The inverse of purchase_recommendation: instead of "what do I need
    for N actions", it answers "what is my N". Two numbers, because one
    would be a lie - `actions` at the measured mean rates and
    `safe_actions` at the worst single recorded run, which burns three
    times the average in garras. No margin here: the margin belongs to
    deciding what to BUY, and applying it on top of the worst case would
    make the pessimistic end look rosier than the realistic one.

    Unreadable counters are skipped rather than guessed; a HUD that says
    nothing answers None.
    """
    per_resource, floors = {}, {}
    for name, rate in BURN_PER_ACTION.items():
        have = (inventory or {}).get(name)
        if have is None:
            continue
        # The nudge keeps binary floats from turning 780/0.78 into 999:
        # the counters are whole numbers and so should the answer look.
        per_resource[name] = math.floor(max(0, have) / rate + 1e-9)
        floors[name] = math.floor(
            max(0, have) / WORST_BURN_PER_ACTION[name] + 1e-9)
    if not per_resource:
        return {"actions": None, "limiting": None, "per_resource": {},
                "safe_actions": None}
    limiting = min(per_resource, key=per_resource.get)
    return {"actions": per_resource[limiting], "limiting": limiting,
            "per_resource": per_resource, "safe_actions": min(floors.values())}


def _thousands(value):
    return f"{value:,}".replace(",", ".")


def format_run_plan(planned_actions, inventory):
    """The pre-run briefing: what N actions cost against what you carry.

    Answers both directions of the question in one screen - "for N
    actions I need X" and "with what I have I reach M" - so the number
    typed at the prompt can be chosen instead of guessed.
    """
    labels = {"steps": "pasos", "attacks": "garras", "dashes": "dashes"}
    rec = purchase_recommendation(planned_actions, inventory)
    readable = [name for name in labels if rec.get(name)]
    if not readable:
        return ("No se pudo leer el inventario en pantalla. Revisa que el "
                "juego esté en DigiWorld y vuelve a intentar.")
    lines = [f"Para {_thousands(planned_actions)} acciones "
             f"(con 15% de margen sobre el consumo medido):"]
    for name in ("steps", "attacks", "dashes"):
        entry = rec.get(name)
        if not entry:
            lines.append(f"  {labels[name]:<7s} contador ilegible")
            continue
        mark = "falta" if entry["deficit"] else "ok"
        lines.append(f"  {labels[name]:<7s} necesitas {entry['need']:>5}   "
                     f"tienes {_thousands(entry['have']):>7}   {mark}")
    lines.append(format_purchase_advice(rec))
    reach = affordable_actions(inventory)
    if reach["actions"] is not None:
        lines.append(
            f"Con lo que llevas alcanzan ~{_thousands(reach['actions'])} "
            f"acciones; el primero en agotarse sería "
            f"{labels[reach['limiting']]}. En la peor corrida medida, "
            f"~{_thousands(reach['safe_actions'])}.")
    return "\n".join(lines)


def format_purchase_advice(rec):
    """Spanish one-liner for the run start."""
    if rec.get("total_shards", 0) <= 0:
        return "Inventario suficiente para el run planeado - no hay que comprar nada."
    parts = []
    labels = {"steps": "pasos", "attacks": "garras", "dashes": "dashes"}
    for name, label in labels.items():
        entry = rec.get(name)
        if not entry or not entry["deficit"]:
            continue
        if "packs" in entry:
            parts.append(f"{entry['packs']} pack(s) de 50 {label} "
                         f"({entry['cost']:,} shards)".replace(",", "."))
        else:
            parts.append(f"{entry['deficit']} {label} "
                         f"({entry['cost']:,} shards)".replace(",", "."))
    total = f"{rec['total_shards']:,}".replace(",", ".")
    return ("Compra recomendada (ratio medido 24 pasos : 1 garra : 0,8 dashes): "
            + ", ".join(parts) + f" | total ~{total} shards")


def milestone_chest_ready(image):
    """Return the milestone chest's tap point when a reward is claimable.

    At every 1,000m the chest by the progress bar gains a magenta '!'
    badge (user captures 2026-08-20). After claiming, the chest stays
    golden until the next scroll but the badge disappears, so the badge -
    combined with the golden chest - is the claim signal. Claiming takes
    two taps on the same point: one opens the Reward overlay, one closes
    it. Costs one numpy pass over 15% of the frame, no extra screenshots.
    """
    a = np.asarray(image.convert("RGB")).astype(int)
    height, width = a.shape[:2]
    y0 = int(height * .65)
    band = a[y0:int(height * .80)]
    r, g, b = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    badge = (r > 200) & (g < 110) & (b > 110) & (b < 210)
    gold = (r > 210) & (g > 150) & (g < 215) & (b < 110)
    area = band.shape[0] * band.shape[1]
    if badge.sum() < area * .0005 or gold.sum() < area * .001:
        return None
    # The badge is the anchor, the tap goes on the chest BODY: the gold
    # cluster within a window around the badge is the chest itself, and
    # taps on the body claim more reliably than taps on the '!' bubble
    # (user observation). Gold far from the badge is the meters text,
    # which grows with distance and dragged the old gold+badge average
    # ~130px left of the chest at 12,000m (run 20260820T192556 event 240
    # tapped (379, 912) with the chest near x=510: the tap opened
    # nothing and the chest went unclaimed).
    ys, xs = np.where(badge)
    badge_x, badge_y = xs.mean(), ys.mean()
    gold_ys, gold_xs = np.where(gold)
    near = ((np.abs(gold_xs - badge_x) < width * .12) &
            (np.abs(gold_ys - badge_y) < band.shape[0] * .8))
    if near.any():
        return int(gold_xs[near].mean()), int(gold_ys[near].mean()) + y0
    return int(badge_x), int(badge_y) + y0


# items_flickering + the burst WAIT were retired 2026-08-21: the per-cell
# suspect filter adjudicates phantoms and the confirmed-item memory holds
# real items through animation frames, so the whole-board flicker guard
# only added 0.4-0.8s of dead time per pickup wave.


def close_reward_overlay(tap, capture, classify, max_taps=5, pause=None):
    """Tap until the board is back; return the taps used.

    Run 20260820T052000: the blind 0.6s close tap fired before the Reward
    overlay accepted input, the overlay stayed open, and the run died on
    five unreliable-board waits. Each tap is now verified with a fresh
    frame; the extra screenshots only happen during a claim.
    """
    for attempt in range(1, max_taps + 1):
        tap()
        if pause is not None:
            pause()
        det = classify(capture())
        if det.state == "digiworld" and det.board:
            return attempt
    return max_taps


# Left margin of the 720x1280 screen, mid-height: outside every centered
# dialog frame (the Stage Failed "Growth Guide" panel starts at x~62) and
# left of the board (x0~77), so on a healthy frame the tap hits inert
# background.
DISMISS_TAP_XY = (20, 640)


def growth_guide_overlay(image):
    """Recognize the 'Growth Guide' panel; report whether the stage failed.

    The panel (user capture 2026-08-21) has a light-gray title bar around
    15-20% of the frame height and a dark gray body below it; when it
    pops because the stage ended, a big red 'Stage Failed' headline sits
    above it. One numpy pass, no OCR.

    The first version also demanded a density of saturated red
    (`r>150 & g<60 & b<70`) from the section frames, measured at 0.0022
    on the fixture with a 0.001 floor. A live capture on 2026-08-25 -
    the same panel, plainly visible on screen - scored 0.00097 and the
    bot walked straight past it: a floor set from ONE capture with a 2.2x
    margin is not a measurement, it is a coincidence. That term is gone.
    What replaced it are the two signals that separate the panel from
    every board fixture by more than an order of magnitude:

        signal            panel (2 captures)   15 board fixtures
        gray title rows   69 and 75            0 in all of them
        dark panel body   .327 and .446        <= .011

    The 'Stage Failed' headline moved to a RELATIVE red test over the top
    22% of the frame (the absolute one clipped the anti-aliased glow):
    .0233 and .0290 on the two captures against <= .0023 on every board.
    """
    a = np.asarray(image.convert("RGB")).astype(int)
    height, width = a.shape[:2]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gray = ((np.abs(r - g) < 18) & (np.abs(g - b) < 18)
            & (r > 120) & (r < 190))
    title_rows = gray[int(height * .10):int(height * .30)].mean(axis=1)
    body = ((np.abs(r - g) < 26) & (np.abs(g - b) < 26)
            & (r > 25) & (r < 95))[int(height * .25):int(height * .82)]
    if (int((title_rows > .15).sum()) < int(height * .02)
            or body.mean() < .10):
        return None
    headline = ((r > 170) & (r > g * 1.8)
                & (r > b * 1.8))[:int(height * .22)]
    return {"stage_failed": bool(headline.mean() > .008)}


# A cell tap may wander this fraction of the cell away from its centre.
# The point stays inside the SAME cell, so nothing about the target
# changes - only the pixel. 20% of a ~110px cell is +-22px, well clear of
# the border even when the board estimate is a few pixels off.
TAP_SAFE_FRACTION = .20


def cell_tap_point(board, cell, jitter=None):
    """Where to tap for `cell`: its centre, moved inside its own area."""
    x, y = bot.cell_center(board, *cell)
    if jitter is None:
        return x, y
    x0, y0, x1, y1 = board
    rx = abs(x1 - x0) / 5 * TAP_SAFE_FRACTION
    ry = abs(y1 - y0) / 5 * TAP_SAFE_FRACTION
    return jitter.point(("cell", tuple(cell)), x, y, rx, ry)


def button_tap_point(point, jitter=None, radius=(10, 6)):
    """Where to tap a HUD button whose centre was located by vision."""
    if jitter is None or point is None:
        return point
    return jitter.point(("button", point), point[0], point[1], *radius)


# The two independently safe places to tap a centred dialog away. The
# first is this bot's inert left margin (DISMISS_TAP_XY); the second is
# the strip below the panel and above the world/home button, which is the
# spot the Android companion uses. An attempt that changed nothing tries
# the other one instead of repeating itself.
DISMISS_POINTS = ((DISMISS_TAP_XY[0] / 720, DISMISS_TAP_XY[1] / 1280),
                  (.50, .865))


def build_overlay_arbiter(strikes):
    """The covers this bot knows, in the order they outrank each other.

    `strikes` is a callable returning the current unreliable-board strike
    count: an unrecognized cover is only *suspected*, so it may not own
    the frame until the board has failed to read twice.
    """
    def growth_guide(image, det=None):
        return growth_guide_overlay(image)

    def suspected_cover(image, det=None):
        return {"strikes": strikes()} if strikes() >= 2 else None

    return overlays.OverlayArbiter([
        overlays.OverlayKind("growth_guide", priority=9, detect=growth_guide,
                             points=DISMISS_POINTS, cooldown=0.0,
                             max_attempts=4),
        overlays.OverlayKind("suspected_cover", priority=1,
                             detect=suspected_cover, points=DISMISS_POINTS,
                             cooldown=0.0, max_attempts=2),
    ])


def out_of_steps(inventory, rejected_streak, threshold=2):
    """True when moves keep bouncing and the stamina counter confirms 0.

    Run 20260820T030401 started with 62 steps, counted down to 1, and then
    burned five rejected taps plus a generic exit 6. Two rejections with a
    confirmed empty counter are enough evidence to stop with a clear
    out-of-steps message instead; an unreadable counter never counts as 0.
    """
    if rejected_streak < threshold or not inventory:
        return False
    steps = inventory.get("steps")
    return steps is not None and steps <= 0


def impossible_player_jump(previous_action, origin, destination, player,
                           single_move):
    """Detection that breaks the one-move law is a misdetection.

    Nothing moves the digi except our taps, and one commanded move
    shifts him at most one cell: after a single move he is at the
    destination (executed) or the origin (tap swallowed or rejected).
    Any other cell is the locator latching onto animation residue.
    Run 20260822T004437 n=15 and n=194, identical signature: pickup at
    (2,1) under a confetti burst, commanded down to (3,1), and the next
    frame 'found' the player back at (1,1) - so the bot tapped (2,1)
    "downward" from the ghost and yanked the real digi back a step.
    Batches are exempt: a 3-move run can be interrupted anywhere along
    its path, so only single moves pin the outcome to two cells."""
    if previous_action != "move" or not single_move:
        return False
    if origin is None or destination is None:
        return False
    return tuple(player) not in (tuple(origin), tuple(destination))


def wall_is_stable(committed, wall_now, done, scrolls_now, ttl=3):
    """Same wall seen on consecutive frames, scroll-adjusted.

    Run 20260821T200525: a 3-pyramid wall one row up was never hunted
    while the bot rode rightward - every scroll shifted the launch one
    column left and the raw-cell comparison read it as a brand-new wall
    each frame. The commitment carries the scroll count at sighting, so
    the expected position moves with the world."""
    if committed is None or wall_now is None:
        return False
    cell, seen_done, seen_scrolls = committed
    expected = (cell[0], cell[1] - (scrolls_now - seen_scrolls))
    return wall_now == expected and done - seen_done <= ttl


def should_hold_for_wall(wall_now, wall_stable, action, reason, holds,
                         max_holds=2):
    """Do not act on the frame of doubt: a fresh wall holds plain moves.

    Wall hunting needs the same launch on two consecutive frames, and
    in the gap the tour acts - run 20260822T153206 n=97-101 stepped
    DOWN toward an orb on the sighting frame and the stabilized hunt
    walked it right back: three wasted steps. A plain move now waits
    one frame while the wall stabilizes. Free grabs and perishable
    rescues still go (they never regret themselves), non-moves are
    never held, and two holds break the stall if the wall flickers."""
    if wall_now is None or wall_stable or holds >= max_holds:
        return False
    if action is None or action[0] != "move":
        return False
    return not reason.startswith(("adjacent item", "orange perishable",
                                  "urgent pickup", "approach dash wall"))


# (should_hold_for_adjacent_suspect retired 2026-08-22: under the
# known-world doctrine an adjacent suspect is always left-band confetti
# that can never be believed or targeted, so there was nothing to wait
# for - the n=49-50 vaiven it once fixed is covered by the sticky TTL.)


# (rejection_needs_grace retired 2026-08-23 with silent_rejection. The
# late-landing tap it defended against - run 20260822T175424 n=2-5, a
# "refused" move the next frame showed had landed - cannot happen to the
# receipt: a late tap still gets charged, and the charge is what the
# runner reads. The "same cell refused twice mints the wall" rule that
# replaced it costs no frame at all, because the first refusal is
# replanned from a state we KNOW did not change.)


def item_cells_of(info):
    """Cells the suspect system and scroll reconciler treat as items.

    Claw cells score claw>.10 with item low BY DESIGN, so the old
    item>.06 set was blind to them: a claw ghost from an over-shifted
    memory walked the bot to an empty cell and neither system could
    see the mismatch (run 20260822T162851 n=176-181)."""
    return frozenset(cell for cell, values in info.items()
                     if values["item"] > .06
                     or values.get("claw", 0.0) > .10)


def committed_wall_dash(committed_wall, player, done, ttl=3, last_dash=None,
                        suspect_cells=(), scrolls_now=None,
                        left_band_risk=False):
    """True when standing on a recently confirmed wall launch cell.

    Wall detection can flicker for one frame right when the bot arrives at
    the launch (run 20260820T023300, events 44-48: reached (4,0), the wall
    blinked out, and the bot paced away and back three times before an
    opportunistic rule finally fired the dash). Walls do not vanish on
    their own, so a launch confirmed within the last few actions is still
    valid: dash.

    A dash consumes the commitment it honored: after the wall dash the
    scroll leaves the player on the same launch column and the broken wall
    stops re-committing, so a commitment not newer than the last dash sent
    fired a second 400-shard dash into an almost empty path (runs
    20260820T031845/032120, one wasted dash each).
    """
    if committed_wall is None:
        return False
    cell = committed_wall[0]
    if scrolls_now is not None and len(committed_wall) > 2:
        cell = (cell[0], cell[1] - (scrolls_now - committed_wall[2]))
    if cell != player:
        return False
    if last_dash is not None and last_dash >= committed_wall[1]:
        return False
    if left_band_risk:
        # Same deference as the strategy-side wall rule: the dash's
        # scroll deletes left-band pickups. Run 20260822T162851 n=52
        # fired this override with a remembered orange at (0,1) and
        # scrolled it off the board. BELIEVED pickups only - the
        # left-band SUSPECT veto retired 2026-08-23 along with the
        # strategy's suspect_risk (docs/review-2026-08-23.md).
        return False
    return done - committed_wall[1] <= ttl


def merge_remembered_items(info, remembered, player):
    """Re-inject remembered pickups that suppression or occlusion hid.

    An item sighted from afar disappears when the big sprite gets close
    (suppress_sprite_leaks wipes its 3x3), which flipped goals every step
    in run 20260820T022548. Remembered cells keep a just-over-threshold
    score so the pathfinder holds course; the player's own cell is never
    reinjected (standing there collects it).
    """
    merged = dict(info)
    for cell, (category, _) in remembered.items():
        if cell == player:
            continue
        values = merged[cell]
        if strategy.is_obstacle(values):
            # The world outranks memory: painting a remembered item
            # over a cell the game now shows as a pyramid made the
            # adjacent grab tap it, and a move tap onto a pyramid
            # EXECUTES a garra (HUD counter audit run 20260822T142042:
            # ~7 attacks spent that the log never sent).
            continue
        if category == "claw":
            # A claw is targeted via its own mask (claw > .10 with item
            # <= .06); patching "item" would disqualify it instead.
            if values.get("claw", 0.0) <= .10 and values["item"] <= .06:
                patched = dict(values)
                patched["claw"] = .12
                merged[cell] = patched
        elif values["item"] <= .06:
            # Memory stores ECONOMIC types; the grid scores only carry
            # color masks. Patch the category's mask plus the
            # discriminator pickup_type needs to round-trip it (crash
            # run 20260821T195439: patched['purple_ticket'] KeyError).
            patched = dict(values)
            mask = {"orange": "orange", "steps": "pink",
                    "purple_ticket": "pink", "dash_orb": "green",
                    "green_ticket": "green"}.get(category, "orange")
            patched[mask] = max(patched.get(mask, 0.0), .07)
            if category == "purple_ticket":
                patched["white"] = max(patched.get("white", 0.0), .06)
            if category == "green_ticket":
                patched["card_green"] = max(patched.get("card_green", 0.0), .04)
            patched["item"] = .07
            merged[cell] = patched
    return merged


def shift_items_left(remembered):
    """Scroll compensation: the world moved one column left."""
    return {(row, col - 1): value
            for (row, col), value in remembered.items() if col - 1 >= 0}


# (shift_items_right retired 2026-08-23. It undid an over-counted scroll,
# which only existed because memory was shifted OPTIMISTICALLY at tap
# time and then argued with the pixel sensor a frame later. Memory now
# shifts once, from the receipt, and never has to walk backwards.)


class StableBoard:
    """Holds the board rectangle still while the detector jitters.

    The grid is FIXED on screen - the doctrine the whole scroll sensor
    is built on says only its CONTENTS move - but the detector returned
    a different rectangle every frame (14 frames, 14 rectangles, 4-8 px
    of jitter). Every derived crop moved with it: the scroll strips had
    different SHAPES, so measure_scroll_px hit its shape guard and
    returned None in 74-85% of frames. The sensor written to replace
    tap-counting was inert most of the time, and the runner fell back
    to the tap count it was built to distrust. Locking cuts that to
    10-16% (measured on runs 20260822T234822, 20260823T033159).

    A detection far from the lock is a real move (a screen change, a
    different layout) and is adopted at once."""

    def __init__(self, tolerance=16):
        self.board = None
        self.tolerance = tolerance

    def settle(self, detected):
        if detected is None:
            return self.board
        detected = tuple(int(v) for v in detected)
        if self.board is None:
            self.board = detected
        elif max(abs(a - b) for a, b in zip(detected, self.board)) > self.tolerance:
            self.board = detected
        return self.board


def board_strip(image, board):
    """Downsampled grayscale of the board's RIGHT 3 COLUMNS only.

    The first version took the whole board and the docstring lied: the
    player sprite - big, static, high-contrast at columns 0-1 -
    anchored the alignment at zero, so real scrolls measured 0 (run
    20260822T172446 n=73-76: detection showed pyramids marching left,
    full-board measured 0.0, right-3-columns measured 1.04 each). The
    left 2 columns are excluded for good."""
    import numpy as np
    x0, y0, x1, y1 = board
    a = np.asarray(image.convert("L"), dtype=float)
    strip = a[y0:y1, x0 + 2 * (x1 - x0) // 5:x1]
    # coarse downsample keeps the correlation cheap and blurs noise
    return strip[::4, ::4]


def measure_scroll_columns(prev_strip, cur_strip, max_cols=3):
    """Columns the world actually scrolled between two settled frames.

    Doctrine 2026-08-22 (user): reconcile by MEASURING, not by counting
    taps. Run 20260822T164337 n=30-32: a latency-swallowed tap left
    memory one column ahead, the re-tap hit the pyramid scrolling in
    (two hidden garras, HUD 41->39), and a dash followed. The board
    strip is compared at shifts 0..max_cols; the best alignment IS the
    scroll. Confetti and sprites are local noise against a whole-board
    alignment. Returns None when the strips are unusable. (Thin wrapper
    over measure_scroll_px, which adds mid-slide detection.)"""
    cols, _ = measure_scroll_px(prev_strip, cur_strip, max_cols)
    return cols


def measure_scroll_px(prev_strip, cur_strip, max_cols=3, slide_tolerance=0.2,
                      strip_cols=3):
    """Pixel-granular scroll measurement with mid-slide detection.

    The grid rectangle stays put while the CONTENTS slide, so
    board_in_motion cannot see a scroll in flight - run 20260822T171206
    took screenshots mid-slide seventeen times, read scroll 0, and
    desynced memory from the world (cannot-move toasts, a garra on an
    empty cell). The strip alignment is searched at ~pixel steps: a
    best offset near a whole column is a settled measurement; anything
    in between means the board is still moving. Returns
    (columns, sliding) or (None, False) when unusable."""
    import numpy as np
    if prev_strip is None or cur_strip is None:
        return None, False
    if prev_strip.shape != cur_strip.shape or prev_strip.shape[1] < 10:
        return None, False
    width = prev_strip.shape[1]
    col_px = max(1, width // strip_cols)
    # At least one full column of overlap: a sliver of empty-vs-empty
    # scores ~0 and steals the argmin from the true alignment.
    max_off = min(max_cols * col_px, width - col_px)
    best_off, best_score = 0, None
    scores = []
    for off in range(0, max_off + 1, 2):
        a = prev_strip[:, off:]
        b = cur_strip[:, :width - off]
        score = float(np.mean(np.abs(a - b)))
        scores.append((score, off))
        if best_score is None or score < best_score:
            best_off, best_score = off, score
    # Confidence: the argmin rewrites every board-memory structure, so
    # a picture that cannot decide must say so. On a low-contrast strip
    # (an empty right band) the alignments at 0, 1 and 2 columns sit
    # within noise of one another and the winner is arbitrary - None
    # means 'trust the tap count', which is the safe answer there
    # (review 2026-08-22, 'physics' lens).
    if float(np.std(prev_strip.astype(float))) < 4.0:
        return None, False
    rivals = [s for s, off in scores if abs(off - best_off) >= col_px]
    if rivals and best_score is not None and min(rivals) < best_score * 1.15:
        return None, False
    cols_f = best_off / col_px
    nearest = int(round(cols_f))
    sliding = abs(cols_f - nearest) > slide_tolerance
    return min(nearest, max_cols), sliding


def confirmed_pickup(detected_info, merged_info, cell):
    """Category of what was collected at `cell`, or None.

    Vision decides: reading the category from the MEMORY-MERGED board
    minted phantom pickups whenever the digi stepped on a stale
    remembered cell - inflating the run stats and, worse, opening a
    confetti burst zone around a place where nothing was collected,
    which then suspected the real items around it (review 2026-08-22).
    Memory stays what it is good for: routing."""
    if detected_info is None:
        return None
    category = item_category(detected_info[cell])
    return category or None


def dash_had_no_effect(inventory_before, inventory_after, player_moved,
                       obstacles_before, obstacles_after):
    """Did the dash tap do nothing at all?

    The old test was 'the player cell did not change', which is true of
    every SUCCESSFUL dash: the dash travels three cells right and the
    world scrolls the same three columns back, so the digi ends where
    it started (review 2026-08-22, 'physics' lens). Paired with 'two
    pyramids on the right before and after' - routine, since new ones
    scroll in behind the broken ones - a working dash could disable
    dashing for the rest of the run.

    The inventory counter settles it: a dash that ran cost one dash.
    Only when the count did NOT drop (or cannot be read at all) does
    the board evidence get a say."""
    before = (inventory_before or {}).get("dashes")
    after = (inventory_after or {}).get("dashes")
    if before is not None and after is not None:
        return after >= before
    return not player_moved and obstacles_after >= obstacles_before


class FrameClock:
    """Ticks once per screenshot.

    Every confetti/reveal window used to be expressed in `done`, which
    counts ACTIONS (done += len(sent), up to three per frame) while the
    animations they bound last a fixed number of FRAMES: after a 3-tap
    batch the two-frame confetti window was already expired on the very
    next frame, so the protection evaporated exactly when the bot moved
    fastest (review 2026-08-22, 'suspects' lens). Memory pruning keeps
    using `done` on purpose - it guards against our own coordinate
    errors per action, not against an animation."""

    def __init__(self):
        self.now = 0

    def tick(self):
        self.now += 1
        return self.now


def should_wait_for_slide(sliding, slide_waits, max_waits=3):
    """Mid-slide WAIT with a retry cap.

    Run 20260822T212332 n=82: the uncapped wait compared every new
    frame against a FROZEN prev_strip, so content that settled at a
    fractional alignment (an item animating in the right band, a
    preview glint) read as 'sliding' forever - 47 straight waits until
    the user killed the run. After max_waits the caller rebases
    prev_strip on the current frame and moves on: one lost measurement
    beats a deadlock."""
    return bool(sliding) and slide_waits < max_waits


# (scroll_shortfall_wait retired 2026-08-23. It existed because the
# pixel sensor could not tell a LATE scroll from a SWALLOWED tap, so it
# bought a frame of silence to find out - 14 of the 186 frames of run
# 20260823T074036. The paw receipt answers the question outright: the
# game either charged the step or it did not, and neither answer is
# improved by waiting. See step_ledger.py.)


def pointless_attack(detected_info, target):
    """A garra may only go to a cell DETECTION shows as a pyramid.

    Run 20260822T171206 n=163: a cannot-move toast minted a phantom
    obstacle, the router attacked it - 200 shards swung at an empty
    cell - and then walked an 8-step detour around a wall that did not
    exist. A phantom vision cannot confirm gets dropped, not hit."""
    return not strategy.is_obstacle(detected_info[tuple(target)])


RESCAN_DELAY = 0.5

ACTION_DELAYS = {
    # Tuned 2026-08-22 after the sensor fix: run 174628 had ONE
    # shortfall in 52 steps, so the scroll floor holds; pickups no
    # longer need to outwait their confetti (known-world ignores it),
    # per the user: 'ya sabemos que genera confeti, simplemente
    # ignorarlo - se queda un poquito trabado ahí'.
    # Re-tuned 2026-08-22b: at 0.30 the game's own hop animation lost
    # the race ~7 grace frames per 200 steps (run 183056), and every
    # grace frame costs ~1.1s - pricier than +0.1s on every move.
    "move": 0.42,
    "move_scroll": 0.60,
    "move_pickup": 0.55,
    "move_pickup_scroll": 0.70,
    "attack": 0.85,
    # Raised 1.30 -> 2.00 on 2026-08-28. The dash animates its own
    # pickups across three columns, and reading the board mid-animation
    # is how the confetti got believed. Timed against the recordings:
    # with a 2.0s gap 10% of post-dash frames still showed five or more
    # items, with 2.2s 5%, with 2.5s 1% (n=346). 2.00 here plus the
    # pipeline lands around 2.5s. The remaining 1% is why the world model
    # also refuses the right-edge amnesty after a dash - a delay is a bet
    # on this machine's timing, and the pipeline just got six times
    # faster. Dashes are now ~3 per hundred actions, so the extra second
    # costs a few seconds a run.
    "dash": 2.00,
}
JITTER_FRACTION = 0.45


def action_delay(kind, scrolled=False, picked_up=False, rand=random.random):
    """Internal pacing per action type (user directive 2026-08-22).

    The CLI interval is gone: timing follows what the game animates.
    A plain step is the floor; a scroll or a pickup must let its
    animation finish or the next tap gets swallowed (run
    20260822T165752 n=6-12: six rapid rights into a lag freeze,
    measured scroll 0); garra and dash animate longest. Jitter is a
    uniform fraction of the base, so fast actions stay fast and the
    rhythm reads human."""
    if kind == "move":
        key = ("move_pickup_scroll" if picked_up and scrolled
               else "move_pickup" if picked_up
               else "move_scroll" if scrolled
               else "move")
    else:
        key = kind if kind in ACTION_DELAYS else "move"
    base = ACTION_DELAYS[key]
    return base * (1.0 + rand() * JITTER_FRACTION)


MAX_DELAY_STRETCH = 1.6
DELAY_STRETCH_UP = 0.2
DELAY_STRETCH_DOWN = 0.05


def next_delay_stretch(current, refused, had_taps=True,
                       cap=MAX_DELAY_STRETCH, up=DELAY_STRETCH_UP,
                       down=DELAY_STRETCH_DOWN):
    """Multiplier on every pacing delay, driven by the game's receipt.

    ACTION_DELAYS was measured on one emulator on one afternoon. The same
    emulator after a cold reboot swallowed 14-19% of taps at that pace
    (runs 20260824T0139-0157) where it had swallowed 3%, and a blunt x1.4
    on every delay brought it back to 6% - the constants were right for
    the machine that day, not for the machine. So the pace answers to the
    receipt: a swallowed tap stretches it fast, and every frame the game
    keeps up relaxes it four times slower, back to the measured base.
    A frame that sent no taps says nothing either way."""
    if not had_taps:
        return current
    if refused:
        return min(cap, current + up)
    return max(1.0, current - down)


def lag_batch_limit(lag_cooldown, size):
    """Single steps while the lag detector cools down.

    A claimed>measured reconciliation means the game swallowed taps:
    batching more into the freeze only feeds it (run 20260822T165752
    n=6-12 fed six)."""
    return 1 if lag_cooldown > 0 else size


# (scroll_overcount, the cell-fingerprint reconciler, retired
# 2026-08-22: superseded by the pixel measurement in
# measure_scroll_columns - one sensor instead of a heuristic.)


def shift_cells_left(cells):
    """Scroll compensation for cell SETS (loop-breaker ban history).

    Run 20260821T220436: the loop breaker banned (0,1) at n=159 during
    an explore ping-pong; nineteen actions later a real orange scrolled
    into that exact cell, sat invisible to the perishable rescue, and
    died off the left edge. Bans mark board content and the content
    moves with the scroll, so bans move with it and retire off-edge."""
    return {(row, col - 1) for (row, col) in cells if col - 1 >= 0}


def modal_overlay_visible(overlay_center, det, min_confidence=.75):
    """A modal overlay covers the board; a pickup animation does not.

    Run 20260821T205929: all five 'overlay visible' episodes were the
    pickup confetti - white Gatomon plus white-bordered cards over blue
    water satisfied the tutorial-card heuristic while the board sat in
    plain sight (state=digiworld, conf .81-.84). Each false modal rolled
    back a move that HAD landed and banned an innocent cell. A real
    modal (the Growth Guide: state=unknown, conf 0.0) degrades board
    detection, so that degradation is now required."""
    if overlay_center is None:
        return False
    return (det.state != "digiworld" or not det.board
            or det.confidence < min_confidence)


def board_in_motion(detected, stable, tolerance=18):
    """The grid rect jumped: the scroll animation is still running.

    Run 20260821T222310 frame 11 (user-spotted): a screenshot mid-scroll
    put the whole board off the grid, a real energy straddled two cells,
    and the classifier saw nothing there. A sudden rect jump is the
    motion signal; the frame must be re-captured, not classified."""
    if detected is None or stable is None:
        return False
    return max(abs(a - b) for a, b in zip(detected, stable)) > tolerance


def remember_pending_reveals(pending, cells, done, ttl=4):
    """Broken-pyramid cells stay legitimate reveal spots for a few frames.

    Run 20260821T222310 n=4-11 (user-confirmed loss): the dash broke the
    pyramid at (1,4), the drop landed at (1,1) after the dash's scroll,
    but the fall animation delayed detection by three frames - past the
    single-frame whitelist - so the real energy was flagged suspect,
    never reached memory, and scrolled off. The whitelist now survives
    the animation and shifts with the scroll like all board memory."""
    updated = dict(pending)
    for cell in cells:
        updated[tuple(cell)] = done + ttl
    return updated


def live_reveal_cells(pending, done):
    """Reveal cells whose grace window is still open."""
    return {cell for cell, expiry in pending.items() if expiry > done}


def explore_followup_budget(reason, direction, remaining):
    """A vertical exploration step never batches.

    With no goals to guard the batch, an explore detour around a pyramid
    rode two cells down when one step plus a fresh look was the whole
    point (run 20260821T225908 n=127, user-spotted: 'why not just round
    the pyramid through the middle?'). Rightward exploration keeps its
    batch - riding straight is what exploring is for."""
    if str(reason).startswith("explore") and direction in ("up", "down"):
        return 0
    return remaining


def warmup_batch_limit(done, limit):
    """One verified cell per frame until the board has history.

    User rule 2026-08-21: the first screens carry no verifiable memory,
    so the opening moves must not blind-batch three taps off a single
    unverified frame (run 20260821T222310 opened with an explore x3 -
    two scrolls - before anything was confirmed)."""
    return 1 if done < 3 else limit


# (silent_rejection and its grace frame retired 2026-08-23. It inferred
# a refusal from the player still standing on the pre-move cell, and its
# own docstring conceded the blind spot: "scroll rides prove nothing -
# riding right leaves the player on the same screen cell by design". The
# paw receipt has no blind spot and needs no grace frame, which cost 9
# of the 186 frames of run 20260823T074036. See step_ledger.refused_tap.)


def should_trust_rejection(player_source, player_score):
    """Was the rejected move issued from a confidently SEEN player?

    User mechanic (2026-08-22): moves are cross-only from the REAL player
    cell and the cell-highlight hints are buggy, so a 'cannot move there'
    toast usually means the believed player cell was wrong - not that the
    board hides a wall. Only a strong direct sighting justifies blaming
    the destination cell; weaker fixes blame the player fix itself."""
    return player_source == "vision" and player_score >= .12


def merge_phantom_obstacles(info, obstacles, done):
    """Cells the game refused to enter read as pyramids for a few frames.

    Run 20260821T203611: ten 'cannot move there' toasts in 200 moves -
    the detector had missed a pyramid, the router walked into it, and the
    next frame often replanned the very same rejected step. The game's
    rejection is ground truth, so the cell blocks routing until the
    ban expires or the world scrolls it away."""
    live = {cell for cell, expiry in obstacles.items() if expiry > done}
    if not live:
        return info
    merged = dict(info)
    for cell in live:
        if cell in merged:
            values = dict(merged[cell])
            values["pyramid"] = max(values.get("pyramid", 0.0), .9)
            # Every pickup channel, not just "item": choose() builds
            # orange_items from "orange" and mid_items from "claw", so
            # zeroing one of the four left the adjacent-pickup rule
            # walking at a cell the tap gate then refused as a pyramid
            # (13 wasted frames across the seven runs of 2026-08-23,
            # three of them the same cell in run 20260823T154134).
            for channel in ("item", "orange", "pink", "green", "claw"):
                if channel in values:
                    values[channel] = 0.0
            merged[cell] = values
    return merged


def compact_state(info, player, remembered):
    """Compact per-frame board state for the event log.

    Every forensic session so far had to reconstruct boards from the
    annotated debug PNGs, which carry no pyramids, no item categories
    and no memory (user question 2026-08-21: the logs were NOT optimal).
    ~200 bytes per event buys exact offline replays."""
    return {
        "player": list(player),
        "items": {f"{r},{c}": (item_category(v) or "item")
                  for (r, c), v in info.items()
                  if is_pickup(v) and (r, c) != tuple(player)},
        "pyramids": sorted([r, c] for (r, c), v in info.items()
                           if strategy.is_obstacle(v)),
        # The step the memory was last SEEN on rides along. Without it a
        # forensic pass can tell that the bot chased a memory and not
        # whether the memory was fresh or stale, which is exactly the
        # question a decision about chasing it turns on (attempt of
        # 2026-08-28 to size that rule died here for want of the number).
        "remembered": {f"{r},{c}": [cat, seen]
                       for (r, c), (cat, seen) in remembered.items()},
    }


def belt_the_pixels_confirm(owed, measured):
    """RETIRED 2026-08-28c. Kept only so the reason survives.

    It capped the world model's advance at what the pixel sensor could
    see, to stop the model running ahead of the animation. The sensor is
    not good enough to hold that veto: on the frames where the belt
    genuinely moves it reads 1 in 41.8%, says nothing in 36.4%, reads 2
    in 10.0% - and reads a flat ZERO in 11.9% (n=1576). One frame in
    eight, the cap froze the model while the world moved.

    What that looks like, run 20260828T212305 n=31-34 (user: "no tomo
    una energia que tenia al lado"): the same orange lands on (2,2),
    then (2,1), then (2,0) as the belt carries it, and because the model
    never advanced, each position is a NEW track with one sighting. It
    stayed suspect the whole way across the board and was never chased.
    The suspect list just grew: [(2,2)], then [(2,1),(2,2)], then
    [(2,0),(2,1),(2,2)].

    The sensor can CONFIRM the receipt; it cannot outvote it. The
    duplicate-track bug this was meant to fix (see
    docs/review-2026-08-28.md section 9) is back to being open, and it is
    the rarer of the two by a wide margin.

    Returns the receipt untouched.
    """
    return owed, 0


def _retired_belt_the_pixels_confirm(owed, measured):
    """Split a receipt-granted scroll into what has landed and what is
    still in flight: returns (advance_now, still_owed).

    The receipt answers "did the game charge that step"; the pixels
    answer "where is everything NOW". Different questions, and the world
    model asks the second, so it must not be fed the first.

    Fed the receipt, the model advanced every track one column while
    vision, still mid-animation, reported the entity where it was: the
    track missed at its new cell, became a believed-unseen memory, and
    the sighting at the old cell opened a SECOND track. One orange, two
    tracks, one column apart. Run 20260828T190229 n=96-100 (user: "iba
    bastante bien hasta que dio un paso atras"): detection (4,2) with
    memory (4,1), then (4,1) with (4,0). The bot took the real one -
    energy 13185 to 13310 - and then spent two paws walking left to its
    own duplicate, where the energy did not move.

    A sensor with nothing to say (None) leaves the receipt standing:
    that is the old behaviour and the common case, and guessing against
    silence would stall the belt instead.
    """
    if measured is None or measured >= owed:
        return owed, 0
    return measured, owed - measured


def dash_scroll_count(player_col):
    """Columns the world scrolls on a dash: clamp-to-column-1 physics.

    A dash advances the digi three cells; the world scrolls only what
    it takes to put him back at column 1 - three columns from a col-1
    launch, but only TWO from column 0. The hardcoded 3 shifted memory
    one column too far on col-0 launches: the remembered orange (3,3)
    became a ghost at the empty cell (3,0) while the real one surfaced
    at (3,1) as a fresh suspect, and the bot grabbed the real one then
    walked left to collect the ghost (run 20260822T153206 n=123-126,
    user PNG debug_0124; same signature n=101-103 with the dash orb)."""
    return player_col + 2


def forget_dash_path(remembered, cells):
    """Everything in a dash's path is collected or destroyed.

    Run 20260821T235432 n=64-65 (user-spotted): the dash collected the
    orange in its path, but its memory entry survived, slid three
    columns with the dash's own shift, and the bot stepped back left to
    grab the ghost."""
    updated = dict(remembered)
    for cell in cells:
        updated.pop(tuple(cell), None)
    return updated


def should_disable_attacks(no_effect_streak):
    """Two consecutive no-effect attacks prove a phantom target.

    Run 20260821T235432 n=155: one attack tap swallowed by the game (the
    pyramid was real, the frame shows it standing) read as a phantom
    pyramid and disabled garras for 25 actions - twelve frames later the
    cornered bot stopped the run. A single swallowed tap retries
    naturally on the next frame."""
    return no_effect_streak >= 2


def should_reenable(disabled_at, done, span=REENABLE_ACTIONS):
    """True once enough actions have passed to justify retrying the consumable."""
    return disabled_at is not None and done - disabled_at >= span


def confirmed_energy(previous, current):
    """Accept a HUD reading only when two consecutive reads roughly agree."""
    if previous is None or current is None:
        return None
    if abs(current - previous) <= ENERGY_READ_TOLERANCE:
        return current
    return None


ENERGY_FINAL_RETRIES = 3
ENERGY_FINAL_PAUSE = 0.45


def final_energy(read, loop_reading, retries=ENERGY_FINAL_RETRIES,
                 pause=time.sleep, wait=ENERGY_FINAL_PAUSE):
    """The closing HUD read, taken after the last pickup stops flying.

    A collected orange animates from the board into the counter and
    covers it for most of a second (run 20260823T142253: the last step
    picked one up, the final screenshot caught the icon mid-flight, and
    a run whose energy the loop had read in 36 of 38 frames reported
    "contador ilegible"). Retry while the animation clears; if it never
    does, the last value the loop itself read is a truthful floor and
    beats discarding the run's headline number.
    """
    for attempt in range(retries + 1):
        value = read()
        if value is not None:
            return value, "final"
        if attempt < retries:
            pause(wait)
    if loop_reading is not None:
        return loop_reading, "loop"
    return None, None


REVERSE_DIRECTION = {"up": "down", "down": "up",
                     "left": "right", "right": "left"}


def receipt_pins_player(had_taps, charged, was_dash, claimed=0):
    """True when the game charged nothing, so nobody moved.

    A garra's animation drags the sprite's centre about a cell, and the
    per-cell locator follows it: run 20260823T154134 n=48-51 attacked
    (4,1) from (3,1), read the player at (2,1), and spent three frames
    walking between two cells to correct a move that never happened.
    The paw counter is the authority the rest of the loop already runs
    on; a dash is the one motion it does not bill, so it is excluded.

    It pins only taps that cost NO paw by nature. A CLAIMED move the game
    did not charge says the opposite thing - the tap was illegal from
    where the player really stands - and pinning the believed cell there
    re-asserts the error with score 1.0: run 20260824T0219 n=27-59 read
    the player one row below the truth (the oversized partner sprite
    spills into the row above), had every tap refused as illegal, and
    burned 20 refusals and 26 waits at 4.54 s per action without ever
    letting vision correct it.
    """
    return (bool(had_taps) and not charged and not was_dash
            and not claimed)


def next_overrule_streak(streak, blocked_direction, chosen_direction):
    """How many times in a row the veto has been overruled.

    The cost guard lets the planner keep a cheap reversal rather than buy
    a garra to avoid it. Once that has happened twice on the same closed
    board the arithmetic flips: the reversal is no longer one wasted paw
    but a loop (run 20260824T051703 n=38-40). No veto armed means no
    evidence either way, so the count stands."""
    if not blocked_direction:
        return streak
    return streak + 1 if chosen_direction == blocked_direction else 0


def refusal_distrusts_vision(claimed, charged):
    """A claimed move the game refused says the believed cell was wrong.

    The resolver's memory bridge keeps handing back the cell the receipt
    just contradicted; run 20260824T0219 spent 33 frames tapping from a
    row the player was not on because nothing ever told the bridge to let
    go. One frame of pure vision is the whole cost of being wrong here."""
    return bool(claimed) and charged < claimed


def next_blocked_direction(current, had_taps, claimed, charged, belt_shift,
                           picked, direction):
    """The direction that would undo the last charged step.

    A charged step that collected nothing and did not scroll leaves the
    board byte-identical, so walking back re-enters a state the strategy
    already judged and two goals that disagree about the two cells trade
    the player between them (run 20260823T143257 n=45-52: six paws, zero
    progress).

    The fact is about the board, not the frame, so a frame that brings
    no receipt - a wait, a hold, a skip - leaves the standing veto
    alone. Recomputing it from an empty receipt is what let run
    20260823T150408 n=70-72 walk back to (3,1) across a
    wall-stabilizing wait.
    """
    if not had_taps:
        return current
    if (claimed and charged == claimed and not belt_shift and not picked
            and direction in REVERSE_DIRECTION):
        return REVERSE_DIRECTION[direction]
    return None


def player_cell(info):
    return max(((p, v["player"]) for p, v in info.items()), key=lambda q: q[1])


def adaptive_batch_limit(requested, item_goals):
    """Allow three clicks only for Batch-2 frames without visible pickups."""
    return 3 if requested == 2 and not item_goals else requested


def is_pickup(values):
    """Any collectible cell: color-mask items or the yellow claw.

    The claw scores low on the color "item" mask (it has its own mask), so
    checking only values["item"] left claw-only boards looking item-free:
    batches grew to 3 moves and overshot the turn cell toward the claw.
    A pyramid's glints trip the claw detector, and a cell cannot be
    both - the pyramid score wins (replay harness 2026-08-22 n=107)."""
    if strategy.is_obstacle(values):
        return False
    return values["item"] > .06 or values.get("claw", 0.0) > .10


def pickup_goals(info, player):
    """All collectible cells except the player's own."""
    return {cell for cell, values in info.items()
            if is_pickup(values) and cell != player}


def is_single_step_approach(reason):
    """Dash approaches advance one verified cell per screenshot.

    Blind follow-ups batch past the launch cell: the batcher extends in
    the same direction and the launch is not an item, so it has no goal
    to measure against and simply keeps going.

    There are THREE approach rules and this guard listed two of them.
    "position for forming wall" arrived later and never got added, which
    is the whole of run 20260828T191457 n=40-46 (user: "al final hizo
    unas vueltas extranisimas perdiendo varios pasos"): the board did not
    change once, the launch stayed (1,1), and the bot walked (2,1) ->
    (2,0) -> (1,0) -> (0,0) -> (1,0) -> (2,0) -> (3,0) - seven paws past
    a launch cell it had been standing next to. Twice it took the right
    first step and the batch carried it two cells beyond.

    (The earlier two: wall approach, and "pair launch" in run
    20260820T180814 events 33-35, which ping-ponged around row 3 instead
    of launching.)"""
    return reason.startswith(("approach dash wall", "pair launch",
                              "position for forming wall"))


def progress(current, total, message, color="36"):
    """Print one compact, colored status line for interactive debug runs."""
    print(f"\033[{color}m{current}/{total}: {message}\033[0m", flush=True)


def format_duration(seconds):
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def progress_summary(current, total, elapsed_seconds):
    percent = round(current * 100 / total) if total else 100
    remaining = (elapsed_seconds / current * (total - current)) if current else 0
    return (f"{current}/{total} ({percent}%) | transcurrido {format_duration(elapsed_seconds)} "
            f"| quedan ~{format_duration(remaining)}")

_DIGIT_TEMPLATES = None


def _normalize_glyph(mask, size=(20, 28)):
    ys, xs = np.where(mask)
    if not len(xs):
        return np.zeros(size[::-1], dtype=bool)
    crop = (mask[ys.min():ys.max()+1, xs.min():xs.max()+1] * 255).astype("uint8")
    resized = Image.fromarray(crop).resize(size, Image.Resampling.BILINEAR)
    return np.asarray(resized) > 100


def _digit_templates():
    global _DIGIT_TEMPLATES
    if _DIGIT_TEMPLATES is not None:
        return _DIGIT_TEMPLATES
    result = {str(digit): [] for digit in range(10)}
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    try:
        # Verdana/Tahoma bold cover the game's wide "1" (flag plus full base
        # bar), which the Arial/Segoe narrow "1" cannot match.
        for font_path in (fonts_dir / "arialbd.ttf", fonts_dir / "segoeuib.ttf",
                          fonts_dir / "verdanab.ttf", fonts_dir / "tahomabd.ttf"):
            if not font_path.exists():
                continue
            for size in range(18, 25):
                font = ImageFont.truetype(str(font_path), size)
                for digit in result:
                    canvas = Image.new("L", (32, 36))
                    ImageDraw.Draw(canvas).text((2, -2), digit, font=font, fill=255)
                    result[digit].append(_normalize_glyph(np.asarray(canvas) > 100))
    except OSError:
        return None
    # Glyphs harvested from real game screenshots (tests/fixtures ground
    # truth) match far better than any system font approximation.
    game_path = Path(__file__).with_name("game_digit_templates.json")
    if game_path.exists():
        try:
            harvested = json.loads(game_path.read_text(encoding="utf-8"))
            for digit, glyphs in harvested.items():
                if digit in result:
                    for glyph in glyphs:
                        result[digit].append(
                            np.array([[char == "1" for char in row] for row in glyph]))
        except (OSError, ValueError):
            pass
    if not all(result.values()):
        return None
    _DIGIT_TEMPLATES = result
    return result


def read_energy_counter(image, dump_path=None):
    """Read the orange HUD counter conservatively; return None if uncertain.

    With dump_path set, the digit region is saved as a small PNG so misreads
    can be audited against the real game glyphs afterwards.
    """
    templates = _digit_templates()
    if templates is None:
        return None
    rgb = np.asarray(image.convert("RGB"))
    top = rgb[:max(1, int(rgb.shape[0] * .15))]
    orange = ((top[:, :, 0] > 200) & (top[:, :, 1] > 55) &
              (top[:, :, 1] < 180) & (top[:, :, 2] < 100))
    ys, xs = np.where(orange)
    if not len(xs):
        return None
    x1, y0, y1 = xs.max(), ys.min(), ys.max()
    if y1 - y0 < 15:
        return None
    roi = top[y0+5:y1-5, x1+4:min(top.shape[1], x1+120)]
    if dump_path is not None:
        try:
            Image.fromarray(roi).save(dump_path)
        except OSError:
            pass
    white = (roi[:, :, 0] > 215) & (roi[:, :, 1] > 215) & (roi[:, :, 2] > 215)
    return _decode_digit_runs(white, templates)


def _decode_digit_runs(mask, templates):
    """Split a boolean glyph mask into digit runs and template-match them."""
    columns = mask.sum(axis=0)
    runs, start = [], None
    for column, count in enumerate(columns):
        if count >= 2 and start is None:
            start = column
        elif count < 2 and start is not None:
            runs.append((start, column)); start = None
    if start is not None:
        runs.append((start, len(columns)))

    digits, previous_end = [], None
    for left, right in runs:
        if previous_end is not None and left - previous_end > 6 and digits:
            break
        previous_end = right
        glyph = mask[:, left:right]
        glyph_y, glyph_x = np.where(glyph)
        if not len(glyph_x) or glyph_y.max() - glyph_y.min() + 1 < 9:
            continue
        # A "1" is the only glyph much narrower than it is tall; judging by
        # aspect ratio keeps the rule valid across HUD font sizes.
        glyph_height = glyph_y.max() - glyph_y.min() + 1
        if right - left <= max(4, glyph_height * .45):
            digits.append("1"); continue
        normalized = _normalize_glyph(glyph)
        ranked = sorted((min(float(np.mean(normalized != item)) for item in candidates), digit)
                        for digit, candidates in templates.items())
        if ranked[0][0] > .18 or ranked[1][0] - ranked[0][0] < .04:
            return None
        digits.append(ranked[0][1])
    if not 1 <= len(digits) <= 6:
        return None
    return int("".join(digits))


def read_inventory_counters(image, dump_path=None):
    """Read the bottom-left HUD counters: stamina steps, garras, dashes.

    Each icon (pink paws, yellow claws, green dash orb) is located by color;
    the dark digits to its right are template-matched. Unreadable counters
    come back as None, never as a guess.
    """
    empty = {"steps": None, "attacks": None, "dashes": None}
    templates = _digit_templates()
    if templates is None:
        return dict(empty)
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    region = rgb[int(height * .80):, :int(width * .45)]
    r = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    b = region[:, :, 2].astype(int)
    icon_masks = {
        "steps": (r > 200) & (b > 150) & (g < 190) & (r > g + 40),
        "attacks": (r > 200) & (g > 160) & (b < 120),
        "dashes": (g > 180) & (r < 180) & (g > b + 40),
    }
    result = dict(empty)
    for name, mask in icon_masks.items():
        ys, xs = np.where(mask)
        if not len(xs):
            continue
        x1 = xs.max()
        # The pink timers left of the icons share its color; only pixels near
        # the icon's right edge define the counter's vertical band.
        near_icon = xs > x1 - 40
        y0, y1 = ys[near_icon].min(), ys[near_icon].max()
        if y1 - y0 < 12:
            continue
        roi = region[max(0, y0 - 4):y1 + 6, x1 + 4:min(region.shape[1], x1 + 96)]
        dark = ((roi[:, :, 0] < 150) & (roi[:, :, 1] < 160) & (roi[:, :, 2] < 175))
        if dump_path is not None:
            try:
                base = Path(dump_path)
                Image.fromarray((dark * 255).astype("uint8")).save(
                    base.with_name(f"{base.stem}_{name}{base.suffix}"))
            except OSError:
                pass
        result[name] = _decode_digit_runs(dark, templates)
    return result


def format_counter(value):
    return f"{value:,}".replace(",", ".")

def item_category(values):
    """Return the pickup's economic type, or None below threshold.

    Delegates to strategy.pickup_type so the collected stats distinguish
    the four pickups the color masks used to conflate (paws vs purple
    ticket, dash orb vs green ticket).
    """
    return strategy.pickup_type(values)


def format_rate(value):
    return f"{value:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


MAX_IDLE_FRAMES = 25


def idle_streak(streak, acted):
    """Frames in a row that sent no tap."""
    return 0 if acted else streak + 1


def idle_exhausted(streak, limit=MAX_IDLE_FRAMES):
    """True once the loop is provably not making progress.

    Every skip and hold in this file is a local "replan and try again",
    and each one is reasonable on its own; nothing bounded how many
    could follow each other. Run 20260823T145105 executed 46 of its 80
    actions and then repeated one refused-garra frame 579 times, so
    --steps was never reached and the run had no way to end. The limit
    sits well above the largest legitimate hold (the unreliable-board
    wait, 5).
    """
    return streak >= limit


def keep_evidence(run_dir, name, image):
    """Save a diagnostic image, or nothing at all when debug is off.

    A normal run leaves the disk untouched (user directive 2026-08-27):
    no screenshots, no log, no run directory. Everything a run used to
    drop by default now waits for --debug, and the call sites ask this
    one function instead of each testing the flag and catching OSError.

    Returns the path written, or None - which is what the event carries,
    so a log read afterwards says plainly that no evidence was kept.
    """
    if run_dir is None:
        return None
    try:
        path = run_dir / name
        image.save(path)
        return str(path)
    except OSError:
        return None


def log_frame(log, event):
    """Write the frame and report whether it produced no action at all.

    A frame whose only action is a WAIT string bought nothing but time;
    counting them here keeps the 11 wait sites from each needing their
    own bookkeeping. With debug off there is no log to write to, and the
    counting still has to happen.
    """
    if log is not None:
        bot.log_event(log, event)
    action = event.get("action")
    return 1 if isinstance(action, str) and action.startswith("WAIT") else 0


def efficiency_report(claimed, charged, waits, frames, elapsed, energy_delta):
    """The two kinds of waste a run can produce, plus its exchange rate.

    A refused tap costs no paw but costs a frame and usually drags a
    re-plan behind it; a wait frame costs time and nothing else. Both
    were invisible in the closing line before 2026-08-23, so a
    pathfinding change could only be judged by watching the emulator.
    energy_per_paw is the number the whole bot exists to raise.
    """
    refused = max(0, claimed - charged)
    return {
        "claimed": claimed,
        "charged": charged,
        "refused": refused,
        "refused_share": refused / claimed if claimed else None,
        "waits": waits,
        "frames": frames,
        "wait_share": waits / frames if frames else None,
        "seconds_per_action": elapsed / charged if charged else None,
        "energy_per_paw": (energy_delta / charged
                           if charged and energy_delta is not None else None),
    }


def format_efficiency(report):
    parts = [f"{report['charged']}/{report['claimed']} taps cobrados"]
    if report["refused"]:
        parts.append(f"{report['refused']} rechazados "
                     f"({report['refused_share']:.0%})")
    parts.append(f"{report['waits']} esperas")
    if report["seconds_per_action"] is not None:
        parts.append(f"{report['seconds_per_action']:.2f}s/accion")
    if report["energy_per_paw"] is not None:
        parts.append(f"{report['energy_per_paw']:.0f} energia/patica")
    return " | ".join(parts)


def run_summary(elapsed_seconds, collected, energy_start=None, energy_end=None):
    total = sum(collected.values())
    tickets = (collected.get("green_ticket", 0) + collected.get("purple_ticket", 0)
               + collected.get("pink", 0) + collected.get("green", 0))
    detected = (f"recogidos: {total} "
                f"(Energía {collected.get('orange', 0)}, "
                f"Garras {collected.get('claw', 0)}, "
                f"Orbes dash {collected.get('dash_orb', 0)}, "
                f"Pasos {collected.get('steps', 0)}, Tickets {tickets})")
    if energy_start is not None and energy_end is not None:
        difference = energy_end - energy_start
        hud = (f"Energía {format_counter(energy_start)} -> {format_counter(energy_end)} "
               f"({difference:+d})")
        if elapsed_seconds > 0:
            per_minute = difference * 60 / elapsed_seconds
            per_hour = difference * 3600 / elapsed_seconds
            hud += f" | {format_rate(per_minute)}/min | {format_rate(per_hour)}/h"
    else:
        hud = "Contador de energía ilegible"
    return f"LISTO | Tiempo total {format_duration(elapsed_seconds)} | {hud} | {detected}"


def show_run_summary(current, total, started_at, collected, energy_start=None,
                     energy_end=None, color="32"):
    message = run_summary(time.monotonic() - started_at, collected, energy_start, energy_end)
    progress(current, total, message, color)

def plan_status(kind, direction, reason, item_count):
    if reason.startswith("approach dash wall"):
        return "Muro de pirámides a la vista - aproximando para el dash"
    if item_count:
        return f"¡Energía a la vista! {item_count} item(s) - recalculando ruta"
    if kind == "dash":
        return "Dash planeado - varios obstáculos al frente"
    if kind == "attack":
        return "Pirámide a la vista - ejecutando ataque seguro"
    labels = {"right": "la derecha", "left": "la izquierda", "up": "arriba", "down": "abajo"}
    return f"Explorando hacia {labels.get(direction, direction)} - {reason}"


def read_ticket_counters(image):
    """Read the top-HUD summon ticket counters (green and purple tickets).

    The three top pills (orange energy, green ticket, purple ticket) share a
    layout: colored icon on the left, white digits on a gray pill. Each icon
    is located by color and the digits to its right are template-matched.
    """
    empty = {"green": None, "purple": None}
    templates = _digit_templates()
    if templates is None:
        return dict(empty)
    rgb = np.asarray(image.convert("RGB"))
    height = rgb.shape[0]
    top = rgb[:max(1, int(height * .06))]
    r = top[:, :, 0].astype(int)
    g = top[:, :, 1].astype(int)
    b = top[:, :, 2].astype(int)
    icon_masks = {
        "green": (g > 150) & (r < 150) & (g > b + 60),
        "purple": (r > 170) & (b > 190) & (g < 150),
    }
    result = dict(empty)
    for name, mask in icon_masks.items():
        ys, xs = np.where(mask)
        if not len(xs):
            continue
        y0, y1, x1 = ys.min(), ys.max(), xs.max()
        if y1 - y0 < 12:
            continue
        roi = top[y0 + 4:y1 - 2, x1 + 4:min(top.shape[1], x1 + 130)]
        if roi.shape[0] < 10:
            continue
        white = (roi[:, :, 0] > 215) & (roi[:, :, 1] > 215) & (roi[:, :, 2] > 215)
        # The pill's white rounded border fills whole rows; digits never do.
        white[white.mean(axis=1) > .6] = False
        result[name] = _decode_digit_runs(white, templates)
    return result


def read_drop_counters(image):
    """All HUD counters a pyramid drop can move, in one flat dict."""
    counters = read_inventory_counters(image)
    tickets = read_ticket_counters(image)
    counters["green_tickets"] = tickets["green"]
    counters["purple_tickets"] = tickets["purple"]
    return counters


def expected_after_move(screen_target, direction):
    """On-screen cell where the player should appear after a committed move.

    Entering zero-based column 2 scrolls the world left, so a rightward move
    into column >=2 leaves the player rendered one column to the left.
    """
    row, col = screen_target
    if direction == "right" and col >= 2:
        return (row, col - 1)
    return (row, col)


def unsafe_move_tap(info, target, suspects=(), remembered=()):
    """A 'move' tap onto a pyramid or an UNKNOWN suspect must not go out.

    A tap onto a cell the game shows as a pyramid EXECUTES a garra.
    HUD counter audit (run 20260822T142042): the attack counter
    dropped ~7 more times than the log sent attacks - every one a move
    tap landing on a pyramid the planner did not see. The guards cut
    that to one hidden garra the very next run (20260822T160202): the
    survivor at n=89 stepped onto the SUSPECT cell (1,1) - confetti
    covering a pyramid the vision could not see. A suspect cell is
    unknown ground: never tap it, wait for adjudication.

    Memory outranks suspicion here exactly as it does in
    drop_remembered_suspects: run 20260822T194747 n=20 refused the
    route to a REMEMBERED orange four times in a row because its cell
    also flickered suspect, and four known oranges paraded off the
    left edge (user: 'no recogió 2 energías')."""
    # Only a pyramid can make a move tap unsafe. Refusing SUSPECT cells
    # too was the blunt answer to confetti hiding a pyramid (run
    # 20260822T160202 n=89, one hidden garra); it turned harmless cards
    # into walls and cost eight taps where six sufficed in run
    # 20260823T033159. The precise answer lives in the world model: a
    # covered pyramid keeps its own track, so this line still refuses
    # it - as a pyramid, which is what it is.
    return strategy.is_obstacle(info[tuple(target)])


def lawful_tap(cell):
    """Game law: with the digi pinned to columns 0-1, a cross move can
    reach column 2 at most - any tap beyond it is invalid by definition
    and answered with 'cannot move to this location'."""
    return cell[1] <= 2


def resolve_player(info, expected):
    """Blend vision with dead reckoning: veto teleports, bridge weak frames.

    Vision wins while it is confident and physically plausible. A confident
    detection more than two cells from the expected position is treated as a
    misdetection when the expected cell still shows any player signal, and a
    weak frame falls back to the expected position instead of stalling.

    Game law (user-confirmed 2026-08-22): the digi only ever stands in
    the two leftmost columns - the scroll returns him there after every
    rightward step. Any player signal beyond column 1 is a misdetection
    (run 20260821T212701 locked onto (2,3) for 31 frames and sprayed
    invalid taps), so those cells are masked before resolving, and an
    unlawful expected position is discarded outright.
    """
    if expected is not None and expected[1] > 1:
        expected = None
    best, score = player_cell(info)
    if best[1] > 1:
        masked = {cell: (values if cell[1] <= 1 else dict(values, player=0.0))
                  for cell, values in info.items()}
        best, score = player_cell(masked)
    memory_score = (info[expected]["player"]
                    if expected is not None and expected in info else 0.0)
    if score >= .08:
        if expected is not None and memory_score >= .02:
            jump = abs(best[0] - expected[0]) + abs(best[1] - expected[1])
            if jump > 2:
                return expected, memory_score, "memory-veto"
        return best, score, "vision"
    if expected is not None and memory_score >= .02:
        return expected, memory_score, "memory"
    return best, score, "vision"


def veto_with_blob(player, score, source, blob):
    """Let a real sprite blob override weak or implausible vision.

    A weak per-cell score next to a sprite blob is the sprite itself leaking
    into a neighboring cell (FM's red torso scores ~0.1 one row above his
    feet, run 20260820T014923), and a weak score far away is an item glow
    (a green ticket hit 0.095 in run 20260820T014121). Memory is inertial
    guesswork and also yields to a live blob (run 20260820T015442 died
    WAIT-gated on memory while the blob knew the answer). Only confident
    vision (>= 0.15, the small-partner range) outranks the blob.
    """
    if blob is None:
        return player, score, source
    if source == "vision" and score >= .15:
        return player, score, source
    blob_cell, blob_score = blob
    return blob_cell, blob_score, "large-sprite"


def attack_result(cell_values):
    """Classify the cell of the previous attack: pyramid gone? drop revealed?"""
    if strategy.is_obstacle(cell_values):
        return {"broken": False, "revealed": None}
    return {"broken": True, "revealed": item_category(cell_values)}


def dash_path_report(info, player, length=3):
    """Count pyramids and visible pickups in the rightward dash range."""
    report = {"pyramids": 0, "visible_items": 0, "cells_seen": []}
    for step in range(1, length + 1):
        cell = (player[0], player[1] + step)
        if cell[1] > 4:
            break
        values = info[cell]
        if strategy.is_obstacle(values):
            report["pyramids"] += 1
        elif item_category(values):
            report["visible_items"] += 1
        report["cells_seen"].append(list(cell))
    return report


def consecutive_right_obstacles(info, player):
    count = 0
    for col in range(player[1] + 1, 5):
        if strategy.is_obstacle(info[(player[0], col)]):
            count += 1
        else:
            break
    return count


def safe_followup_moves(info, player, first_target, direction, count, goals=None):
    """Return safe (screen_target, source_cell_checked) follow-up moves.

    Entering zero-based column 2 scrolls the world left. The Digimon returns
    visually to column 1, while the next right neighbor corresponds to the
    old column 3 that is already visible in the current screenshot.
    """
    if count <= 0 or direction == "left":
        return []
    dr, dc = DIR_DELTA[direction]
    results = []
    goals = set(goals or ())
    # ONE anchor, chosen from where the player stands, and every extra
    # tap has to get closer to THAT goal.
    #
    # The old version took the min over every goal on each step, and the
    # comment below already knew the hole: a move can trade
    # distance-to-A for distance-to-B. Guarding with `>=` closes the
    # flat trade and not the descending one. Run 20260828T172224 n=103
    # (user report): player at (0,1), orange at (0,3) behind the pyramid
    # at (0,2), a steps card at (4,1). One step down to (1,1) is the
    # whole detour - from there the belt walks the orange in. The batch
    # added a second down to (2,1) because it was closer to the CARD,
    # which the tour had already pruned out of the plan. Two paws for a
    # goal nobody was going to.
    #
    # The anchor is measured from the player, not from first_target, so
    # it is the goal the tour itself would have picked first.
    anchor = (min(goals, key=lambda g: (abs(player[0]-g[0]) + abs(player[1]-g[1]), g))
              if goals else None)
    previous_distance = (abs(first_target[0]-anchor[0])
                         + abs(first_target[1]-anchor[1]) if anchor else None)
    if direction == "right" and first_target[1] >= 2:
        offset = 1
        screen_player = (first_target[0], first_target[1] - 1)
    else:
        offset = 0
        screen_player = first_target
    for _ in range(count):
        screen_target = (screen_player[0] + dr, screen_player[1] + dc)
        checked_cell = (screen_target[0], screen_target[1] + offset) if direction == "right" else screen_target
        if not (0 <= checked_cell[0] < 5 and 0 <= checked_cell[1] < 5):
            break
        cell = info[checked_cell]
        if strategy.is_obstacle(cell):
            break
        # This is where the Android planner's corridorClear would go, and
        # the reason it does not sit here: a batched tap IS dispatched
        # blind, so it must stay harmless when the game swallows the
        # previous one. Their planner taps absolute cells, so a swallowed
        # tap slides the whole chain onto cells nobody validated, and
        # they answer that with a free corridor plus one column of
        # margin. The belt makes the same guarantee exact instead of
        # approximate: the screen cell tapped at step k holds, after j
        # swallowed scrolls, the world cell `checked_cell - j`, and every
        # one of those is a cell an earlier iteration already validated
        # (j = 0 is the caller's own first target). The corridor is
        # correct by construction, so the extra margin could only refuse
        # batches that are provably safe. test_corridor_margin.py pins
        # the property, because it lives in this offset arithmetic and
        # nothing else would notice if a future edit lost it.
        if anchor:
            distance = (abs(checked_cell[0]-anchor[0])
                        + abs(checked_cell[1]-anchor[1]))
            # Strictly closer, not merely no-worse: overshooting the
            # route's turn cell cost six moves in run 20260821T200525
            # n=353-359.
            if distance >= previous_distance:
                break
            previous_distance = distance
        results.append((screen_target, checked_cell))
        # Never plan beyond a pickup because its animation changes the frame.
        if is_pickup(cell):
            break
        if direction == "right" and screen_target[1] >= 2:
            offset += 1
            screen_player = (screen_target[0], screen_target[1] - 1)
        else:
            screen_player = screen_target
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--steps", type=int, default=10)
    # --interval/--jitter retired 2026-08-22 (user directive): pacing is
    # internal now - see ACTION_DELAYS/action_delay. Fast where nothing
    # animates, slower where the game swallows taps. The flags are still
    # ACCEPTED so existing launch commands keep working, but ignored.
    p.add_argument("--interval", type=float, default=None,
                   help="ignored: pacing is internal per action type")
    p.add_argument("--jitter", type=float, default=None,
                   help="ignored: pacing is internal per action type")
    p.add_argument("--batch-size", type=int, default=2, choices=(1, 2, 3))
    # One switch for everything a run leaves on disk. A normal run is
    # silent: no run directory, no screenshots, no events log. The
    # old name is still accepted so existing launch commands work.
    p.add_argument("--debug", "--debug-screenshots", action="store_true",
                   dest="debug",
                   help="keep the run directory: screenshots, "
                        "diagnostics and events.jsonl")
    p.add_argument("--plan-only", action="store_true",
                   help="read the HUD, print what --steps would cost, and "
                        "exit without tapping anything")
    p.add_argument("--verbose", action="store_true", help="human-readable status for every scan")
    p.add_argument("--progress-percent", type=int, default=0, help="compact update interval in percent")
    p.add_argument("--min-confidence", type=float, default=.80)
    p.add_argument("--adb", default=bot.ADB_DEFAULT)
    p.add_argument("--serial", default=bot.SERIAL_DEFAULT)
    p.add_argument("--out", type=Path, default=Path("outputs"))
    args = p.parse_args()
    if args.interval is not None or args.jitter is not None:
        print("Aviso: --interval/--jitter ya no aplican - los tiempos "
              "son internos por tipo de acción (ACTION_DELAYS).")
    if args.steps <= 0:
        raise SystemExit("--steps must be positive")

    try:
        args.adb = bot.resolve_adb(args.adb)
        args.serial = bot.resolve_serial(args.adb, args.serial)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 10

    if args.plan_only:
        # One screenshot, no taps, no run directory: the launcher asks
        # this before committing so the number of actions can be CHOSEN
        # against the inventory instead of guessed and then rescued with
        # a mid-run purchase.
        try:
            print(format_run_plan(args.steps,
                                  read_drop_counters(
                                      bot.screenshot(args.adb, args.serial))))
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"No se pudo leer la pantalla: {exc}", file=sys.stderr)
            return 10
        return 0

    # Nothing is written unless the run was asked to keep evidence.
    # run_dir and log stay None otherwise, and every write site is built
    # to take that: see keep_evidence() and log_frame().
    run_dir = log = None
    if args.debug:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        run_dir = args.out / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        log = run_dir / "events.jsonl"
    if args.verbose:
        progress(0, args.steps, "Debug iniciado - primer escaneo", "32")
    done = 0
    started_at = time.monotonic()
    progress_step = max(1, (args.steps * args.progress_percent + 99) // 100) if args.progress_percent else 0
    next_progress = progress_step
    collected = {"orange": 0, "claw": 0, "dash_orb": 0, "steps": 0,
                 "green_ticket": 0, "purple_ticket": 0}
    energy_start = None
    last_energy_read = None
    last_loop_energy = None
    inventory_start = None
    dash_stock = None
    pending_attack_inv = None
    expected_player = None
    expected_rollback = None
    last_refused = None
    last_single_move = False
    memory_streak = 0
    attacks_enabled = True
    dashes_enabled = True
    attacks_disabled_at = None
    dashes_disabled_at = None
    loop_strikes = 0
    banned_targets = {}
    ban_history = set()
    remembered_items = {}
    # Columns scrolled since the last decision frame: the exact shift for
    # the phantom-appearance check (guessing it let ghosts hide behind
    # coincidental mappings, run 20260820T184744 events 105/136).
    scrolls_since_frame = 0
    # Belt the receipt has granted but the pixels have not shown yet.
    pixels_owe = 0
    # The paw ledger: what the game charged us for the taps still awaiting
    # their receipt. `pending_taps` is emptied the moment the counter is
    # read again, so a WAIT frame cannot swallow a scroll.
    paw_count = None
    pending_taps = []
    pending_player = None
    total_scrolls = 0
    prev_strip = None
    frame_clock = FrameClock()
    world = world_model.WorldModel()
    slide_waits = 0
    lag_cooldown = 0
    committed_wall = None
    wall_holds = 0
    last_dash = None
    chest_cooldown = 0
    last_attack = None
    previous_action = None
    previous_attack_target = None
    previous_dash_player = None
    previous_dash_obstacles = 0
    pending_dash = None
    previous_direction = None
    pending_picked = False
    # Cells the player has stood on since the world last changed.
    # Cleared by the belt moving or by a pickup landing, because either
    # one makes every cell worth standing on again.
    barren_stands = set()
    wait_frames = 0
    frames_seen = 0
    idle_frames = 0
    idle_abort = False
    stamina_exhausted = False
    zero_paw_frames = 0
    taps_claimed = 0
    taps_charged = 0
    delay_stretch = 1.0
    blocked_direction = None
    previous_reason = None
    suspect_holds = 0
    stable_board = None
    board_lock = StableBoard()
    unreliable = 0
    player_unreliable = 0
    # One owner per frame: while a cover is recognized, it decides, and
    # the explorer waits. The strike count is what promotes an
    # unrecognized cover from "suspected" to "owner".
    tap_jitter = safe_tap.TapJitter()
    overlay_arbiter = build_overlay_arbiter(lambda: unreliable)
    overlay_waits = 0
    overlay_evidence_saved = 0
    phantom_obstacles = {}
    pending_reveals = {}
    settle_waits = 0
    no_action_waits = 0
    attack_noeffect_streak = 0
    first_move_dest = None
    last_move_player_source = None
    last_move_player_score = 0.0
    distrust_player = False
    overrule_streak = 0
    rejected_streak = 0
    recent_states = []

    while done < args.steps:
        frames_seen += 1
        idle_frames = idle_streak(idle_frames, acted=False)
        if idle_exhausted(idle_frames):
            idle_abort = True
            print(f"Sin avance: {idle_frames} cuadros seguidos sin ejecutar "
                  "ninguna accion. Se corta la corrida para no gastar tiempo "
                  "en vacio; revisa la ultima captura en la carpeta del run.")
            break
        image = bot.screenshot(args.adb, args.serial)
        frame_clock.tick()
        det = bot.classify(image)
        stamp = datetime.now(timezone.utc).isoformat()
        event = {"time_utc": stamp, "next_index": done, "detection": bot.asdict(det)}
        if args.verbose:
            progress(done, args.steps, "Escaneando tablero y recalculando ...", "90")

        # Milestone chest: claim as soon as the magenta badge lights up.
        # Two taps on the same point (open Reward, close it); the energy
        # credits on the next scroll, so both reads are logged for the
        # analyzer. The cooldown keeps the check from re-firing while the
        # claimed chest is still golden.
        if chest_cooldown:
            chest_cooldown -= 1
        else:
            chest_point = milestone_chest_ready(image)
            if chest_point is not None:
                # Fast claim: tap opens the Reward, then verified taps
                # close it - each close tap is confirmed against a fresh
                # frame until the board is back (up to 5 tries).
                claim = {"tap_xy": list(chest_point),
                         "energy_before": read_energy_counter(image)}
                bot.adb(args.adb, args.serial, "shell", "input", "tap",
                        str(chest_point[0]), str(chest_point[1]))
                time.sleep(.8)
                claim["close_taps"] = close_reward_overlay(
                    tap=lambda: bot.adb(args.adb, args.serial, "shell",
                                        "input", "tap", str(chest_point[0]),
                                        str(chest_point[1])),
                    capture=lambda: bot.screenshot(args.adb, args.serial),
                    classify=bot.classify,
                    pause=lambda: time.sleep(.5))
                event["action"] = "CLAIM: milestone chest"
                # A tap that misses the chest opens nothing and the close
                # loop reports instant "success" (run 20260820T192556:
                # close_taps=1, chest never claimed). Verify on a fresh
                # frame: badge gone = claimed; still lit = retry next pass.
                claim["verified"] = milestone_chest_ready(
                    bot.screenshot(args.adb, args.serial)) is None
                event["milestone_claim"] = claim
                # 3 frames cover the badge's fade-out; 20 blocked the
                # NEXT chest when it lit up right after a claim (run
                # 20260820T192556: the 12,000m badge appeared 19 frames
                # after the 11,000m claim and was never claimed).
                chest_cooldown = 3 if claim["verified"] else 0
                if not claim["verified"] and args.verbose:
                    progress(done, args.steps,
                             "Cofre no reclamado - reintentando", "33")
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             "Cofre de milestone reclamado", "32")
                continue

        if modal_overlay_visible(bot.tutorial_overlay_center(image), det):
            if previous_action == "attack":
                attacks_enabled = False
                attacks_disabled_at = done
                previous_action = None
                event["action"] = "WAIT: attacks disabled after rejection"
            elif previous_action == "dash":
                dashes_enabled = False
                dashes_disabled_at = done
                previous_action = None
                pending_dash = None
                event["action"] = "WAIT: dashes disabled after rejection"
            else:
                if previous_action == "move" and expected_rollback is not None:
                    # The overlay right after a move is usually the game's
                    # "cannot move there" toast: the move did not happen, so
                    # dead reckoning must not believe it did.
                    expected_player = expected_rollback
                    event["expected_rollback"] = list(expected_rollback)
                    expected_rollback = None
                    rejected_streak += 1
                    if (first_move_dest is not None and
                            should_trust_rejection(last_move_player_source,
                                                   last_move_player_score)):
                        # Issued from a confidently seen player: the game
                        # just proved that cell is blocked even if the
                        # detector saw it free. Route around it.
                        phantom_obstacles[first_move_dest] = done + 6
                        event["phantom_obstacle"] = list(first_move_dest)
                    else:
                        # Weak or inferred player fix: the rejection most
                        # likely means the believed cell was wrong, so the
                        # next resolution runs on pure vision - no memory
                        # bridge, no buggy highlight-cross fallback.
                        distrust_player = True
                        event["player_distrust"] = {
                            "source": last_move_player_source,
                            "score": round(last_move_player_score, 3)}
                    if out_of_steps(read_inventory_counters(image),
                                    rejected_streak):
                        event["action"] = "STOP: out of steps (stamina 0)"
                        wait_frames += log_frame(log, event)
                        print("Pasos agotados: el contador de estamina marca 0 "
                              "y el juego rechaza cada movimiento. Se regeneran "
                              "por debajo de 100, o se compran con shards "
                              "(2000 = 50 pasos).")
                        show_run_summary(done, args.steps, started_at, collected,
                                         energy_start, read_energy_counter(image),
                                         "33")
                        return 7
                    if rejected_streak >= 5:
                        # Five straight rejected taps mean the believed cell
                        # is wrong in a way no locator is correcting; stop
                        # with evidence instead of burning the step budget.
                        event["action"] = "STOP: moves repeatedly rejected"
                        event["evidence"] = keep_evidence(
                            run_dir, "rejected_moves_evidence.png", image)
                        wait_frames += log_frame(log, event)
                        show_run_summary(done, args.steps, started_at, collected,
                                         energy_start, read_energy_counter(image), "33")
                        return 6
                overlay_waits += 1
                event["action"] = f"WAIT: overlay visible ({overlay_waits}/15)"
                # Run 20260821T203611: ten overlay episodes in 200 moves ate
                # taps and forced replans, and no frame of any overlay was
                # ever saved - the single biggest evidence gap of that
                # forensic session. Every episode's first frame is kept:
                # each toast marks a suboptimal move worth diagnosing
                # (user request 2026-08-22).
                if overlay_waits == 1:
                    event["evidence"] = keep_evidence(
                        run_dir, f"overlay_evidence_{done:04d}.png",
                        bot.diagnostic(image, det))
                    if event["evidence"]:
                        overlay_evidence_saved += 1
                if overlay_waits >= 15:
                    # A persistent overlay (e.g. an unclaimed milestone popup)
                    # would otherwise hang the run silently forever.
                    event["action"] = "STOP: persistent overlay"
                    event["evidence"] = keep_evidence(
                        run_dir, "overlay_stop_evidence.png", image)
                    wait_frames += log_frame(log, event)
                    show_run_summary(done, args.steps, started_at, collected,
                                     energy_start, read_energy_counter(image), "33")
                    return 5
            wait_frames += log_frame(log, event)
            if args.verbose: progress(done, args.steps, str(event["action"]), "33")
            time.sleep(RESCAN_DELAY); continue

        overlay_waits = 0
        # (Rejection accounting moved below the player resolution: toasts
        # are invisible to detection since the confetti gate, so a refused
        # move is recognized by the player standing still instead.)
        if det.state != "digiworld" or not det.board or det.confidence < args.min_confidence:
            unreliable += 1
            event["action"] = f"WAIT: unreliable board ({unreliable}/5)"
            # The arbiter owns the frame while a cover is on it: a
            # recognized Growth Guide panel outranks a merely suspected
            # popup, each attempt moves to the other known-safe point,
            # and the cover is only released when it stops being seen.
            # (Its cooldown is expressed in frames here, and both covers
            # are configured to allow one attempt per frame.)
            decision = overlay_arbiter.observe(frame_clock.now, image, det,
                                               image.size)
            if decision.owner is not None:
                event["overlay"] = dict(decision.evidence,
                                        kind=decision.owner,
                                        attempt=decision.attempt)
            if decision.kind == "stop":
                event["action"] = f"STOP: {decision.reason}"
                wait_frames += log_frame(log, event)
                print(f"Cubierta sin cerrar: {decision.reason}.")
                show_run_summary(done, args.steps, started_at, collected,
                                 energy_start, read_energy_counter(image),
                                 "33")
                return 2
            if decision.kind == "dismiss":
                x, y = safe_tap.point(decision.point[0], decision.point[1],
                                      6, 6, bounds=image.size)
                bot.adb(args.adb, args.serial, "shell", "input", "tap",
                        str(x), str(y))
                event["dismiss_tap"] = [x, y]
                if args.verbose:
                    label = ("Popup sospechado - tap fuera del panel"
                             if decision.owner == "suspected_cover" else
                             "Panel Growth Guide detectado - cerrando")
                    if decision.evidence.get("stage_failed"):
                        label = ("Stage Failed + Growth Guide - cerrando "
                                 "para continuar")
                    progress(done, args.steps, label, "33")
            wait_frames += log_frame(log, event)
            if args.verbose: progress(done, args.steps, "Tablero inestable - nuevo escaneo", "33")
            if unreliable >= 5:
                show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
                return 2
            time.sleep(RESCAN_DELAY); continue
        unreliable = 0
        if energy_start is None:
            current_read = read_energy_counter(
                image,
                run_dir / "energy_roi_start.png" if run_dir else None)
            energy_start = confirmed_energy(last_energy_read, current_read)
            last_energy_read = current_read
            if args.verbose and energy_start is not None:
                progress(done, args.steps, f"Energía inicial: {format_counter(energy_start)}", "93")
        if inventory_start is None:
            reading = read_drop_counters(image)
            if any(value is not None for value in reading.values()):
                inventory_start = reading
                event["inventory_start"] = reading
                if reading and reading.get("dashes") is not None:
                    dash_stock = reading["dashes"]
                # Shopping advice for the whole planned run, from measured
                # burn rates - printed once, before spending anything.
                recommendation = purchase_recommendation(
                    args.steps - done, reading)
                event["purchase_recommendation"] = recommendation
                print(format_purchase_advice(recommendation))

        # Per-frame energy timeline: makes milestone rewards (+1000 spikes)
        # distinguishable from gradual per-meter accrual in the log.
        event["energy"] = read_energy_counter(image)
        if event["energy"] is not None:
            # Kept for the closing summary: a pickup animation can cover
            # the counter exactly when the run ends (see final_energy).
            last_loop_energy = event["energy"]

        # ---- the game's receipt for the taps still owed one ----
        # The grid is furniture: it never moves. Its CONTENTS ride a belt
        # that advances exactly one column when a CHARGED step carries the
        # player from column 1 into column 2 (user doctrine 2026-08-23).
        # So the scroll stopped being a pixel inference: the game charges a
        # pink paw or it does not. Read here, before any wait can `continue`
        # past it, and consumed at the reconciliation below - a WAIT frame
        # leaves the taps pending and the reference untouched, so the delta
        # still spans exactly the taps it should. 12 ms a frame.
        raw_paws = read_inventory_counters(image)["steps"]
        paws_now = step_ledger.sane_reading(
            paw_count, raw_paws, step_ledger.move_taps(pending_taps))
        # The whole receipt hangs off this one number, so the log carries
        # it raw: run 20260824T015248 n=8-18 refused six taps in a row and
        # the log could not say whether the game swallowed them or the HUD
        # counter was simply unreadable that frame.
        event["paws"] = {"raw": raw_paws, "sane": paws_now, "ref": paw_count}

        # Zero steps is the end of the run, not a bad frame. The game
        # refuses every move and says so in a toast the bot cannot read,
        # so nothing in the loop noticed: run 20260828T172224 spent its
        # last 17 frames and 20 seconds at zero, eight of them still
        # tapping and seven of those refused (user report, 2026-08-28).
        # Two consecutive readings, because one unreadable HUD frame must
        # not end a healthy run - the observed stall had seventeen.
        zero_paw_frames = zero_paw_frames + 1 if paws_now == 0 else 0
        if zero_paw_frames >= 2:
            stamina_exhausted = True
            log_frame(log, dict(event, status="out_of_steps"))
            print("Pasos agotados: el contador de estamina marca 0, asi que "
                  "el juego ya no cobra ningun movimiento. Se regeneran por "
                  "debajo de 100, o se compran con shards (2000 = 50 pasos).")
            show_run_summary(done, args.steps, started_at, collected,
                             energy_start, read_energy_counter(image), "33")
            return 7

        if stable_board is None:
            stable_board = det.board
        elif board_in_motion(det.board, stable_board):
            # Only look while the grid is at rest (user rule 2026-08-21):
            # a moving frame classified with the stale rect misses items
            # straddling cell borders. Wait and re-capture; after three
            # tries proceed with the stable rect so the run cannot stall.
            settle_waits += 1
            if settle_waits <= 3:
                event["action"] = f"WAIT: board in motion ({settle_waits}/3)"
                event["board_motion"] = {"detected": list(det.board),
                                         "stable": list(stable_board)}
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             "Tablero en movimiento - espero a que asiente",
                             "33")
                time.sleep(.4)
                continue
            event["board_correction"] = {
                "detected": list(det.board),
                "used": list(stable_board),
                "reason": "rejected sudden grid jump",
            }
            det = bot.Detection(det.state, det.confidence, stable_board,
                                det.reason + "; stable board retained")
        if not board_in_motion(det.board, stable_board):
            settle_waits = 0
        # The motion check above needs the RAW detection; every crop
        # below needs a rectangle that holds still. The detector jitters
        # 4-8 px per frame on a grid that never moves, which changed the
        # scroll strip's SHAPE and made measure_scroll_px bail out in
        # 74-85% of frames - the pixel sensor was inert and the runner
        # was quietly back to counting taps.
        det = bot.Detection(det.state, det.confidence,
                            board_lock.settle(det.board), det.reason)

        cur_strip = board_strip(image, det.board)
        measured, board_sliding = measure_scroll_px(prev_strip, cur_strip,
                                                    max_cols=2)
        # Logged beside the pixel verdict: a "sliding" frame that the
        # receipt says charged nothing would be pure latency. Measured
        # over 340 frames it never happened (5 sliding verdicts, all with
        # a charged step behind them), so the gate that would have skipped
        # those waits was deleted rather than kept as unpaid complexity.
        receipt_charged = step_ledger.charged_steps(
            paw_count, paws_now, step_ledger.move_taps(pending_taps))
        # Telemetry: without it a wait frame said only "sliding" and the
        # pixel reading behind the verdict had to be re-derived from PNGs.
        event["scroll"] = {"measured": measured, "sliding": bool(board_sliding),
                           "receipt_charged": receipt_charged}
        if should_wait_for_slide(board_sliding, slide_waits):
            # The grid stands still while its CONTENTS slide: this
            # screenshot caught the scroll in flight. Acting on it
            # desynced memory 17 times in run 20260822T171206. The taps
            # stay pending and the paw reference untouched, so the receipt
            # below still spans exactly the steps it should.
            slide_waits += 1
            event["action"] = (f"WAIT: board content sliding "
                               f"({slide_waits}/3)")
            wait_frames += log_frame(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Contenido del tablero en movimiento - espero", "33")
            time.sleep(0.6)
            continue
        if board_sliding:
            # Cap exhausted (run 20260822T212332 n=82: 47 straight
            # sliding waits against a frozen reference). The content
            # settled somewhere our old strip cannot recognize: rebase
            # the reference on the CURRENT frame, skip this one
            # measurement, and let the loop continue.
            measured = None
        slide_waits = 0
        prev_strip = cur_strip

        # ---- one quantity, one order of authority ----
        # How many of the taps we sent did the game actually take? The
        # receipt answers ~99% of frames; the pixel sensor fills in when a
        # digit misreads; only if both stay silent do we fall back to
        # assuming our own taps landed. There is no second opinion to
        # argue with, and nothing to WAIT for: an uncharged tap did not
        # happen, which is a fact to replan from, not a maybe to sit out.
        # (This replaced the shortfall wait - 14 of 186 frames of run
        # 20260823T074036 spent doing nothing - the grace frames for taps
        # "not landed yet", and the reconcile-by-shifting-memory-back-and-
        # forth that followed both.)
        claimed = step_ledger.move_taps(pending_taps)
        charged = step_ledger.charged_steps(paw_count, paws_now, claimed)
        charge_source = "paws"
        if charged is None and previous_action != "dash":
            # A dash's jump is out of the strip's range and deterministic
            # anyway (launch column + 2), so there is nothing to measure.
            charged = step_ledger.charge_matching_shift(pending_taps, measured)
            charge_source = "pixels"
        if charged is None:
            charged = claimed
            charge_source = "assumed"
        ledger_refused = None
        # Captured before pending_taps is emptied further down: the
        # resolver runs after that reset, and reading the list there
        # made the pin dead code (run 20260823T155203 n=9 still let the
        # garra animation move the player a row).
        receipt_pin = receipt_pins_player(bool(pending_taps), charged,
                                          previous_action == "dash",
                                          claimed=claimed)
        if pending_taps:
            event["ledger"] = {"claimed": claimed, "charged": charged,
                               "source": charge_source}
            ledger_refused = step_ledger.refused_tap(pending_taps, charged)
            if pending_player is not None:
                expected_player = step_ledger.landing(pending_taps, charged,
                                                      pending_player)
        belt_shift = step_ledger.conveyor_shift(pending_taps, charged)
        for _ in range(belt_shift):
            remembered_items = shift_items_left(remembered_items)
            phantom_obstacles = shift_items_left(phantom_obstacles)
            banned_targets = shift_items_left(banned_targets)
            pending_reveals = shift_items_left(pending_reveals)
            ban_history = shift_cells_left(ban_history)
        scrolls_since_frame += belt_shift
        taps_claimed += claimed
        taps_charged += charged
        # A charged step that collected nothing and did not scroll leaves
        # the board byte-identical: walking back re-enters a state the
        # strategy already judged, and two goals that disagree about the
        # two cells will trade the player between them forever (run
        # 20260823T143257 n=45-52, six paws for zero progress). The
        # receipt is what makes this safe to assert - a refused tap never
        # moved anyone, so it never blocks anything.
        blocked_direction = next_blocked_direction(
            blocked_direction, bool(pending_taps), claimed, charged,
            belt_shift, pending_picked, previous_direction)
        # The same receipt that settles the belt settles this memory:
        # a belt that moved or a pickup that landed makes every cell on
        # the board worth standing on again. Only the CLEAR belongs here;
        # the cell is added once the player is resolved, some forty lines
        # below - adding it here read `player` before this frame assigned
        # it and killed the first frame of every run with
        # UnboundLocalError (reported live 2026-08-28).
        if belt_shift or pending_picked:
            barren_stands = set()
        if pending_taps:
            pending_picked = False
        if blocked_direction:
            # Logged so a back-step in the footage can be told apart from
            # a veto that fired and was overruled by the cost guard.
            event["no_back_step"] = blocked_direction
            event["overrule_streak"] = overrule_streak
        delay_stretch = next_delay_stretch(delay_stretch, charged < claimed,
                                           had_taps=bool(pending_taps))
        event["delay_stretch"] = round(delay_stretch, 3)
        if refusal_distrusts_vision(claimed, charged):
            # The believed cell just got called illegal: resolve this
            # frame on pure vision, no memory bridge (see the function).
            distrust_player = True
        if charged < claimed:
            # The game swallowed taps: it is lagging. Single steps for the
            # next two decisions instead of feeding batches into a freeze.
            lag_cooldown = 2
        # The receipt is consumed here, so the reference always advances -
        # keeping a stale count against emptied taps would make the next
        # delta span steps already accounted for. An unreadable frame
        # costs exactly one fallback, never a drifting ledger.
        paw_count = paws_now
        pending_taps = []
        pending_player = None

        info = strategy.cells(image, det.board)
        # After a rejected move with a weak player fix, the resolution runs
        # on pure vision once: no memory bridge and no highlight-cross,
        # because the rejection itself says the believed cell was wrong.
        player, player_score, player_source = resolve_player(
            info, None if distrust_player else expected_player)
        # The red sprite blob proved the most stable locator for oversized
        # partners; it also vetoes item-glow false positives that sneak just
        # over the vision threshold. The buggy highlight cross stays last.
        large = strategy.find_large_player(
            image, det.board,
            item_cells={cell for cell, values in info.items()
                        if values["item"] > .06})
        player, player_score, player_source = veto_with_blob(
            player, player_score, player_source, large)
        if (player_source == "vision" and player_score < .08
                and not distrust_player):
            cross = strategy.player_from_highlights(info, expected=expected_player)
            if cross is not None:
                player, player_score, player_source = cross, .30, "highlight-cross"
        if receipt_pin and expected_player is not None:
            # The receipt outranks the locator: see receipt_pins_player.
            player, player_score, player_source = expected_player, 1.0, "receipt"
        distrust_player = False
        # Where the player actually stands, now that every source has had
        # its say: the barren memory records cells the bot OCCUPIED, not
        # cells it hoped to occupy.
        barren_stands.add(tuple(player))
        # The receipt already said whether the tap executed, so there is
        # nothing to infer from where the player is standing and nothing
        # to sit out a grace frame for. (silent_rejection admitted in its
        # own docstring that it could not judge a scroll ride - it lands
        # on the same screen cell by design - and its grace frame cost 9
        # of the 186 frames of run 20260823T074036.) A first refusal is
        # replanned from a state we KNOW did not change; the same cell
        # refused twice is a wall the detector missed.
        if ledger_refused is not None:
            rejected_streak += 1
            event["refused_tap"] = {"cell": list(ledger_refused),
                                    "streak": rejected_streak}
            if ledger_refused == last_refused:
                phantom_obstacles[ledger_refused] = done + 6
                event["phantom_obstacle"] = list(ledger_refused)
            last_refused = ledger_refused
            if args.verbose:
                progress(done, args.steps,
                         f"El juego no cobró el paso hacia "
                         f"{list(ledger_refused)} - replanifico", "33")
        elif previous_action == "move":
            rejected_streak = 0
            last_refused = None
        ghost_player = impossible_player_jump(previous_action, expected_rollback,
                                              expected_player, player,
                                              last_single_move)
        if ghost_player:
            event["player_ghost"] = {"detected": list(player),
                                     "lawful": [list(expected_rollback),
                                                list(expected_player)]}
        expected_rollback = None
        memory_streak = memory_streak + 1 if player_source == "memory" else 0
        if player_source != "vision":
            event["player_resolution"] = {"cell": list(player), "source": player_source,
                                          "score": round(player_score, 3)}
        if ((player_source == "vision" and player_score < .08)
                or memory_streak > 2 or player[1] > 1 or ghost_player):
            player_unreliable += 1
            event["action"] = f"WAIT: player score {player_score:.3f} ({player_unreliable}/5)"
            wait_frames += log_frame(log, event)
            if args.verbose: progress(done, args.steps, "Posición del jugador insegura - nuevo escaneo", "33")
            if player_unreliable >= 5:
                event["action"] = "STOP: five consecutive unreliable player frames"
                event["evidence"] = keep_evidence(
                    run_dir, "player_stop_evidence.png",
                    bot.diagnostic(image, det))
                wait_frames += log_frame(log, event)
                show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
                return 3
            time.sleep(1.0); continue
        player_unreliable = 0
        occluded_cells = set()
        if player_source == "large-sprite":
            # A big sprite's own colors read as pickups in the cells its body
            # covers; wipe them so the bot stops chasing its own wings. Items
            # sighted from afar are remembered so getting close (and wiping
            # their cell) does not make the goal flicker away.
            info = strategy.suppress_sprite_leaks(info, player)
            # The wiped cells are unobservable, not empty: the model is
            # told so instead of memory being hand-fed (the old
            # workaround wrote straight into remembered_items).
            occluded_cells = {(player[0] + dr, player[1] + dc)
                              for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                              if 0 <= player[0] + dr < 5
                              and 0 <= player[1] + dc < 5}
        # (The separate claw-sighting loop retired 2026-08-21: claws are
        # ordinary confirmed pickups now - remember_confirmed_items
        # records them with the same suspect gating as everything else.)
        # Memory is recorded from this pre-merge snapshot further down, so
        # a remembered cell can never refresh its own timestamp through
        # the just-over-threshold patch the merge injects.
        detected_info = info
        if remembered_items:
            info = merge_remembered_items(info, remembered_items, player)
        # Standing on a cell PROVES it is walkable: a phantom under the
        # player's feet is a lie left over from a false rejection (run
        # 20260822T175424 - the late tap landed after the refusal
        # minted the phantom, and the wall math then saw a "pyramid"
        # in the player's own cell and launched one step back).
        phantom_obstacles.pop(tuple(player), None)
        # Standing on a cell also COLLECTS whatever it held: an orphan
        # memory under the player froze the tour on a prize it was
        # standing on (replay harness 2026-08-22, BLIND-TOUR class -
        # 'explore' while a remembered orange sat under its own feet).
        remembered_items.pop(tuple(player), None)
        # A cell cannot be a remembered ITEM and a phantom OBSTACLE at
        # once: choose() wants it, the tap gate vetoes it, and the bot
        # deadlocks for frames (replay harness 2026-08-22, n=107 of run
        # 183056: claw memory + stale phantom on (2,2), four identical
        # refused decisions). A contradictory belief is no belief -
        # drop both sides and let fresh vision decide.
        for cell in set(remembered_items) & set(phantom_obstacles):
            remembered_items.pop(cell, None)
            phantom_obstacles.pop(cell, None)
        # Same law against DETECTED pyramids: a remembered item on a
        # cell the screen shows as a pyramid is a contradicted belief -
        # the merge rightly refuses to paint it, so it can only linger
        # as dead weight (replay harness n=101 of run 183056). The
        # world outranks memory: drop it now; if the pyramid was a
        # one-frame flicker, the next sighting re-records the item.
        for cell in [c for c in remembered_items
                     if strategy.is_obstacle(detected_info[c])]:
            remembered_items.pop(cell, None)
        phantom_obstacles = {cell: expiry
                             for cell, expiry in phantom_obstacles.items()
                             if expiry > done}
        info = merge_phantom_obstacles(info, phantom_obstacles, done)
        # ---- ONE world-model update replaces the six-stage stack ----
        # Fresh appearances, the two-frame carryover, burst holds,
        # sticky left-band holds, remembered-suspect drops and the
        # clean-miss decay each grew from one field bug and ended up
        # disagreeing with one another (docs/review-2026-08-22.md).
        # They are gone: every entity is a TRACK whose identity
        # survives the scroll and survives being covered, classified
        # once at birth by where it can physically have come from.
        preview = strategy.sixth_column_preview(image, det.board)
        pending_reveals = {cell: expiry
                           for cell, expiry in pending_reveals.items()
                           if expiry > frame_clock.now}
        detected_items, detected_pyramids = {}, set()
        for cell, values in detected_info.items():
            if strategy.is_obstacle(values):
                detected_pyramids.add(cell)
                continue
            category = strategy.pickup_type(values)
            if category:
                detected_items[cell] = category
        # ---- the receipt/pixel seam -----------------------------
        # The receipt answers "did the game charge that step"; the pixels
        # answer "where is everything NOW". Different questions, and the
        # model asks the second, so it must not be fed the first.
        #
        # Feeding it the receipt advanced every track one column while
        # vision, still mid-animation, reported the entity where it was:
        # the track missed at its new cell, became a believed-unseen
        # memory, and the sighting at the old cell opened a SECOND track.
        # One orange, two tracks, one column apart. Run 20260828T190229
        # n=96-100 (user: "iba bastante bien hasta que dio un paso
        # atras"): detection (4,2) with memory (4,1), then (4,1) with
        # (4,0). The bot took the real one - energy 13185 to 13310 - and
        # then spent two paws walking left to its own duplicate, where
        # the energy did not move.
        #
        # So the model advances only as far as the pixels admit and the
        # rest rides to the next frame. When the sensor has nothing to
        # say (None) the receipt stands, which is the old behaviour and
        # the common case.
        #
        # Tried first and reverted: reconciling the duplicate inside the
        # model, handing a lost track's history to a same-category twin
        # one shift to the right. It merges two REAL neighbours whenever
        # the left one is collected on the same frame, and the replay
        # corpus caught it (20260823T142253 n=32).
        belt_owed = scrolls_since_frame + pixels_owe
        model_shift, pixels_owe = belt_the_pixels_confirm(belt_owed, measured)
        if pixels_owe:
            event["belt_in_flight"] = {"receipt": belt_owed,
                                       "pixels": measured}
        world.observe({"items": detected_items,
                       "pyramids": detected_pyramids},
                      shift=model_shift, player=player,
                      revealed=live_reveal_cells(pending_reveals,
                                                 frame_clock.now),
                      preview=preview, occluded=occluded_cells,
                      edge_explains=previous_action != "dash")
        suspect_items = world.suspect_cells()
        # Memory is simply the believed tracks vision cannot see right
        # now - no separate store, no TTL, no ghost-dropping rules.
        detected_cells_now = item_cells_of(detected_info)
        remembered_items = {cell: (category, done)
                            for cell, category in world.believed_items().items()
                            if cell not in detected_cells_now}
        if remembered_items:
            info = merge_remembered_items(info, remembered_items, player)
        # A pyramid the confetti is covering right now still blocks: its
        # track outlives the card painted over it, and the planner must
        # see it as the obstacle it is rather than have the whole
        # neighbourhood suspected on its behalf.
        covered_pyramids = {cell for cell in world.believed_pyramids()
                            if cell not in detected_pyramids}
        if covered_pyramids:
            info = merge_phantom_obstacles(
                info, {cell: done + 1 for cell in covered_pyramids}, done)
        total_scrolls += scrolls_since_frame
        scrolls_since_frame = 0
        # Detection-only: logging the merged board painted remembered
        # ghosts as real items and a forensic pass adjudicated the
        # debug_0124 ghost walk as a "real orange rescue" against the
        # user's own eyes (2026-08-22). Memory travels separately in
        # "remembered"; "items" is what the screen actually showed.
        event["board"] = compact_state(detected_info, player, remembered_items)
        if suspect_items:
            event["suspect_items"] = sorted(list(cell) for cell in suspect_items)
        if preview is not None and any(preview):
            event["sixth_column"] = preview
        item_goals = pickup_goals(info, player)
        # The log records `detected_info` - the board BEFORE the merges -
        # while every decision is taken on `info`, the board after them.
        # Three forensic passes on 2026-08-28 ended at that seam with
        # "the difference has to be state the log never showed", and the
        # fourth is run 20260829T002643 n=103: the logged board carries
        # an orange at (4,1) one step below the bot, the bot explored
        # right past it (user: "decidio no recoger una energia"), and the
        # batch sizer recorded "no visible items" on the same frame - so
        # the planner's board had no pickup on it and the log cannot say
        # which merge removed it. Replaying the frame every way the
        # recorded state allows takes the orange, so the answer is not in
        # the strategy. This line is what the next run needs to say it in
        # one place: what the PLANNER saw, not what the eyes did.
        if item_goals != {cell for cell, values in detected_info.items()
                          if is_pickup(values) and cell != tuple(player)}:
            event["planner_goals"] = sorted(list(c) for c in item_goals)
        # Batch-2 is adaptive: on an item-free board it may safely advance up
        # to three cells. Any visible pickup immediately restores the more
        # careful two-click limit.
        effective_batch_size = lag_batch_limit(
            lag_cooldown,
            warmup_batch_limit(done,
                               adaptive_batch_limit(args.batch_size,
                                                    item_goals)))
        if previous_action == "attack" and previous_attack_target is not None:
            result = attack_result(info[previous_attack_target])
            inv_after = (read_drop_counters(image)
                         if pending_attack_inv is not None else None)
            event["pyramid_result"] = dict(result,
                                           target_cell=list(previous_attack_target),
                                           scores=info[previous_attack_target],
                                           attacks_before=(pending_attack_inv or {}).get("attacks"),
                                           attacks_after=(inv_after or {}).get("attacks"),
                                           counters_before=pending_attack_inv,
                                           counters_after=inv_after)
            pending_attack_inv = None
            attack_noeffect_streak = (attack_noeffect_streak + 1
                                      if not result["broken"] else 0)
            if not result["broken"] and not should_disable_attacks(
                    attack_noeffect_streak):
                # A single swallowed tap (run 20260821T235432 n=155: real
                # pyramid, still standing) retries naturally next frame.
                event["attack_state"] = {
                    "status": "no visual effect - retrying before disabling",
                    "target_cell": list(previous_attack_target)}
            elif not result["broken"]:
                attacks_enabled = False
                attacks_disabled_at = done
                previous_action = None
                event["attack_state"] = {
                    "status": "disabled: previous attack had no visual effect",
                    "target_cell": list(previous_attack_target),
                }
                # A no-effect attack with garras in stock means we attacked a
                # phantom pyramid; keep the frame so it can be diagnosed.
                event["attack_state"]["evidence"] = keep_evidence(
                    run_dir, f"phantom_attack_{done:04d}.png",
                    bot.diagnostic(image, det))
            previous_attack_target = None
        if previous_action == "dash" and previous_dash_player is not None:
            dash_inv_before = (pending_dash or {}).get("inventory_before")
            if pending_dash is not None:
                after_dump = (run_dir / f"energy_roi_dash_{done:04d}_after.png"
                              if run_dir else None)
                energy_after = read_energy_counter(image, after_dump)
                energy_before = pending_dash["energy_before"]
                event["dash_result"] = {
                    "pyramids_in_path": pending_dash["path"]["pyramids"],
                    "visible_items_in_path": pending_dash["path"]["visible_items"],
                    "energy_before": energy_before,
                    "energy_after": energy_after,
                    "energy_delta": (energy_after - energy_before
                                     if energy_before is not None and energy_after is not None
                                     else None),
                    "inventory_before": pending_dash.get("inventory_before"),
                    "inventory_after": read_drop_counters(image),
                }
                inv_after = event["dash_result"]["inventory_after"]
                if inv_after and inv_after.get("dashes") is not None:
                    dash_stock = inv_after["dashes"]
                pending_dash = None
            current_right_obstacles = consecutive_right_obstacles(info, player)
            if (previous_dash_obstacles >= 2 and current_right_obstacles >= 2
                    and dash_had_no_effect(
                        dash_inv_before,
                        (event.get("dash_result") or {}).get("inventory_after"),
                        player_moved=(player != previous_dash_player),
                        obstacles_before=previous_dash_obstacles,
                        obstacles_after=current_right_obstacles)):
                dashes_enabled = False
                dashes_disabled_at = done
                event["dash_state"] = {
                    "status": "disabled: previous dash had no visual effect",
                    "player_cell": list(player),
                    "right_obstacles_before": previous_dash_obstacles,
                    "right_obstacles_after": current_right_obstacles,
                }
            previous_action = None
            previous_dash_player = None
            previous_dash_obstacles = 0
        recent_states.append((player, tuple(sorted(item_goals))))
        recent_states = recent_states[-12:]
        loop_guard = loop_guard_tripped(recent_states)
        loop_strikes = loop_strikes + 1 if loop_guard else 0
        if explore_bounce(loop_guard, item_goals, previous_reason):
            loop_strikes = LOOP_STRIKES_TO_BAN
        banned_targets = {cell: expiry for cell, expiry in banned_targets.items()
                          if expiry > done}
        if loop_strikes >= LOOP_STRIKES_TO_BAN:
            cells_to_ban = set(item_goals)
            if not cells_to_ban and len(recent_states) >= 2:
                # Explore-phase pacing: ban both bounce cells so the explorer
                # is pushed out of the pocket instead of ping-ponging in it.
                cells_to_ban = {recent_states[-1][0], recent_states[-2][0]}
            expiry = (float("inf") if any(cell in ban_history for cell in cells_to_ban)
                      else done + TARGET_BAN_ACTIONS)
            for cell in cells_to_ban:
                banned_targets[cell] = expiry
                ban_history.add(cell)
            event["loop_breaker"] = {
                "banned_cells": sorted(list(cell) for cell in cells_to_ban),
                "until_action": None if expiry == float("inf") else expiry,
            }
            if args.verbose:
                progress(done, args.steps, "Loop detectado - objetivo ignorado", "33")
            loop_strikes = 0
            recent_states = []
        if not attacks_enabled and should_reenable(attacks_disabled_at, done):
            attacks_enabled = True
            attacks_disabled_at = None
            event["attack_state"] = {"status": "re-enabled: drops may have refilled attacks"}
        if not dashes_enabled and should_reenable(dashes_disabled_at, done):
            dashes_enabled = True
            dashes_disabled_at = None
            event["dash_state"] = {"status": "re-enabled: drops may have refilled dashes"}
        wall_now = (strategy.nearest_dash_wall(info, player, preview=preview)
                    if dashes_enabled else None)
        wall_stable = wall_is_stable(committed_wall, wall_now, done,
                                     total_scrolls)
        if wall_now is not None:
            committed_wall = (wall_now, done, total_scrolls)
        # What the loop breaker has closed off is invisible in the log
        # otherwise, and it is passed to choose() as ignored_targets - so
        # a forensic pass sees the bot walk past a pickup with no reason
        # given anywhere. Run 20260828T213035 n=72 (user: "decidio tomar
        # el camino que no las tomaba y era el mismo") could not be
        # settled for want of exactly this line: replaying the frame the
        # planner takes the card, so the difference has to be state the
        # log never showed.
        if banned_targets:
            event["banned_targets"] = sorted(list(cell)
                                             for cell in banned_targets)
        action, reason = strategy.choose(info, previous_direction,
                                         attacks_enabled, dashes_enabled,
                                         ignored_targets=(set(banned_targets.keys())
                                                          | suspect_items),
                                         player=player, preview=preview,
                                         hunt_walls=wall_stable,
                                         suspect_cells=suspect_items,
                                         dash_stock=dash_stock,
                                         blocked_direction=blocked_direction,
                                         allow_paid_detour=overrule_streak >= 1,
                                         barren_cells=barren_stands)
        left_band_risk = any(
            cell[1] <= 2 and strategy.pickup_type(info[cell])
            not in (None, "purple_ticket", "green_ticket", "steps")
            for cell in item_goals)
        if (action is not None and action[0] != "dash" and dashes_enabled and
                wall_now is None and committed_wall_dash(committed_wall, player,
                                                         done, last_dash=last_dash,
                                                         suspect_cells=suspect_items,
                                                         scrolls_now=total_scrolls,
                                                         left_band_risk=left_band_risk)):
            action, reason = ("dash", player, "right"), "committed wall dash"
            committed_wall = None
        if corridor_dash_due(action, last_attack, done, preview, dashes_enabled,
                             suspect_cells=suspect_items, player=player,
                             left_band_risk=left_band_risk):
            action, reason = ("dash", player, "right"), "corridor dash"
        if (dashes_enabled and should_hold_for_wall(wall_now, wall_stable,
                                                    action, reason,
                                                    wall_holds)):
            wall_holds += 1
            event["reason"] = reason
            event["action"] = (f"WAIT: wall at {list(wall_now)} stabilizing "
                               f"({wall_holds}/2)")
            wait_frames += log_frame(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Muro a la vista sin confirmar - espero un frame", "33")
            time.sleep(.4)
            continue
        wall_holds = 0
        if should_hold_for_suspects(reason, item_goals, suspect_items,
                                    suspect_holds):
            suspect_holds += 1
            event["reason"] = reason
            event["action"] = ("WAIT: suspects pending confirmation "
                               f"{sorted(list(c) for c in suspect_items)}")
            wait_frames += log_frame(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Sospechosos sin confirmar - espero un frame", "33")
            time.sleep(.4)
            continue
        suspect_holds = 0
        if action is None and not attacks_enabled:
            # Run 20260821T235432 n=167: boxed at (4,1) by three real
            # pyramids twelve frames after a phantom attack disabled the
            # garras - the run died at 82% with 77 garras in stock. A
            # cornered bot re-arms and breaks out.
            attacks_enabled = True
            attacks_disabled_at = None
            event["attack_state"] = {
                "status": "re-enabled: cornered with no safe action"}
            action, reason = strategy.choose(info, previous_direction,
                                             attacks_enabled, dashes_enabled,
                                             ignored_targets=(set(banned_targets.keys())
                                                              | suspect_items),
                                             player=player, preview=preview,
                                             hunt_walls=wall_stable,
                                             suspect_cells=suspect_items,
                                             blocked_direction=blocked_direction,
                                             allow_paid_detour=overrule_streak >= 1,
                                             barren_cells=barren_stands)
        if action is None:
            # One unreadable frame must not kill a run: rescan a few
            # times before giving up.
            no_action_waits += 1
            # 5, not 3: 'boxed by suspects' legitimately holds up to the
            # sticky TTL (4 frames) before the surroundings adjudicate.
            if no_action_waits < 5:
                event["action"] = f"WAIT: no safe action ({no_action_waits}/5)"
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             "Sin acción segura - nuevo escaneo", "33")
                time.sleep(.4)
                continue
            event["action"] = "STOP: no safe action"
            wait_frames += log_frame(log, event)
            if args.verbose: progress(done, args.steps, "STOP - sin acción segura", "31")
            show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
            return 4
        no_action_waits = 0
        kind, target, direction = action
        if args.verbose:
            color = "93" if item_goals else "36"
            progress(done, args.steps, plan_status(kind, direction, reason, len(item_goals)), color)
        event["reason"] = reason
        event["batch_limit"] = effective_batch_size
        if effective_batch_size == 3 and args.batch_size == 2:
            event["batch_mode"] = "adaptive-3: no visible items"
        sent = []
        frame_picked = False
        frame_scrolled = False

        # Approach moves toward a dash launch go one cell per screenshot so a
        # vertical approach can never batch past the launch row.
        approaching_wall = is_single_step_approach(reason)

        # Precompute and visualize the batch before sending any input.
        planned = [target]
        if kind == "move" and not approaching_wall and not is_pickup(info[target]):
            remaining = (0 if loop_guard else
                         min(effective_batch_size - 1, args.steps - done - 1))
            planned.extend(p[0] for p in safe_followup_moves(
                info, player, target, direction, remaining, item_goals))
        if args.debug:
            debug = bot.diagnostic(image, det)
            draw = ImageDraw.Draw(debug)
            x0, y0, x1, y1 = det.board
            def box(cell, color, width=4):
                row, col = cell
                xa = round(x0 + col*(x1-x0)/5); xb = round(x0 + (col+1)*(x1-x0)/5)
                ya = round(y0 + row*(y1-y0)/5); yb = round(y0 + (row+1)*(y1-y0)/5)
                draw.rectangle((xa+3, ya+3, xb-3, yb-3), outline=color, width=width)
            box(player, (255, 255, 0), 5)
            for cell, values in info.items():
                if values["item"] > .06 and cell != player:
                    box(cell, (255, 0, 255), 3)
            for number, cell in enumerate(planned, 1):
                box(cell, (255, 80, 0), 5)
                cx, cy = bot.cell_center(det.board, *cell)
                draw.text((cx-5, cy-8), str(number), fill=(255,255,255))
            safe_stamp = stamp.replace(":", "").replace("+", "_")
            event["debug"] = keep_evidence(
                run_dir, f"debug_{done:04d}_{safe_stamp}.png", debug)

        if kind == "dash":
            control = bot.dash_button(image)
            if control is None:
                dashes_enabled = False
                dashes_disabled_at = done
                event["action"] = "WAIT: dash button missing"
                wait_frames += log_frame(log, event)
                if args.verbose: progress(done, args.steps, "Dash no disponible - replanificando", "33")
                continue
            dash_path = dash_path_report(info, player)
            event["dash_path"] = dash_path
            dash_dump = (run_dir / f"energy_roi_dash_{done:04d}_before.png"
                         if run_dir else None)
            pending_dash = {"path": dash_path,
                            "energy_before": read_energy_counter(image, dash_dump)}
            pending_dash["inventory_before"] = read_drop_counters(image)
            dash_xy = button_tap_point(control, tap_jitter)
            bot.adb(args.adb, args.serial, "shell", "input", "tap",
                    str(dash_xy[0]), str(dash_xy[1]))
            sent.append({"type": "dash", "adb_xy": list(dash_xy)})
            if dash_stock is not None:
                dash_stock = max(0, dash_stock - 1)
            expected_player = None
            # The dash consumes any wall commitment; the world scrolls
            # only what clamps the digi back to column 1 (3 from a
            # col-1 launch, 2 from col 0) and memory shifts with it.
            last_dash = done
            committed_wall = None
            remembered_items = forget_dash_path(remembered_items,
                                                dash_path["cells_seen"])
            dash_shift = dash_scroll_count(player[1])
            for _ in range(dash_shift):
                remembered_items = shift_items_left(remembered_items)
                phantom_obstacles = shift_items_left(phantom_obstacles)
                banned_targets = shift_items_left(banned_targets)
                ban_history = shift_cells_left(ban_history)
                pending_reveals = shift_items_left(pending_reveals)
            scrolls_since_frame += dash_shift
            # No reveal window after a dash: it breaks and collects in
            # the same motion, so nothing it touches ever stays on the
            # board. Only a garra leaves a drop (game rule, user
            # 2026-08-22); the dash-path window only ever admitted
            # pickup confetti as phantom items.
            first_move_dest = None
        else:
            if kind == "move" and not lawful_tap(target):
                # Defense in depth: no tap ever goes beyond column 2.
                event["action"] = f"SKIP: unlawful tap at {list(target)}"
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             f"Tap ilegal a {list(target)} suprimido - "
                             "replanificando", "33")
                time.sleep(RESCAN_DELAY)
                continue
            if kind == "attack" and pointless_attack(detected_info, target):
                # A garra only goes to a visually confirmed pyramid: a
                # phantom obstacle minted by a cannot-move toast took a
                # 200-shard swing at an empty cell (run 20260822T171206
                # n=163) and then forced an 8-step detour around a wall
                # that did not exist. Drop the phantom, replan.
                phantom_obstacles.pop(tuple(target), None)
                # The eyes just denied this pyramid at the instant of the
                # swing, which outranks a track built from earlier
                # frames. Without this the belief is immortal and mints
                # the same refused garra forever (run 20260823T145105:
                # 579 frames, zero actions).
                world.refute(tuple(target))
                event["action"] = f"SKIP: garra at visually empty {list(target)}"
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             f"Garra a celda vacía {list(target)} suprimida - "
                             "replanificando", "33")
                time.sleep(RESCAN_DELAY)
                continue
            if kind == "move" and unsafe_move_tap(info, target, suspect_items,
                                                  remembered_items):
                # The tap would land on a pyramid (executes a garra -
                # ~7 hidden attacks in run 20260822T142042) or on an
                # unadjudicated suspect (confetti can hide a pyramid:
                # run 20260822T160202 n=89 tapped 'up' through one).
                if strategy.is_obstacle(info[tuple(target)]):
                    remembered_items.pop(tuple(target), None)
                    phantom_obstacles[tuple(target)] = done + 6
                    event["action"] = f"SKIP: move onto pyramid at {list(target)}"
                    note = "pirámide"
                else:
                    event["action"] = f"SKIP: move onto suspect at {list(target)}"
                    note = "sospechoso"
                wait_frames += log_frame(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             f"Tap sobre {note} en {list(target)} suprimido - "
                             "replanificando", "33")
                time.sleep(RESCAN_DELAY)
                continue
            x, y = cell_tap_point(det.board, target, tap_jitter)
            if kind == "attack":
                pending_attack_inv = read_drop_counters(image)
                last_attack = (target[0], done)
                pending_reveals = remember_pending_reveals(
                    pending_reveals, [target], frame_clock.now)
            bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
            sent.append({"type": kind, "target_cell": list(target),
                         "direction": direction, "adb_xy": [x, y]})
            # A tap is a CLAIM until the game charges a paw for it. The
            # belt is advanced by the receipt at the top of the next
            # frame, never here: shifting five memory stores on the way
            # out and undoing the ones the pixels disagreed with on the
            # way in was the reprocessing the user asked us to delete.
            if pending_player is None:
                pending_player = player
            expected_rollback = player
            expected_player = (player if kind == "attack"
                               else expected_after_move(target, direction))
            first_move_dest = (expected_after_move(target, direction)
                               if kind == "move" else None)
            last_move_player_source = player_source
            last_move_player_score = player_score
            if kind == "move":
                # Stepping onto a cell collects whatever it held: its
                # memory dies before the belt relabels the column.
                remembered_items.pop(tuple(target), None)
            if kind == "move" and direction == "right" and target[1] >= 2:
                # The belt itself waits for the receipt; only the pacing
                # needs to know a scroll animation is on its way. (The
                # wall commitment deliberately survives it: wall_is_stable
                # carries the scroll count at sighting and adjusts the
                # expected launch column. Clearing it here made a wall
                # seen while riding rightward permanently "unstable" -
                # run 20260822T004437 n=48-49 exploring right past a
                # 3-pyramid wall one step down, never hunted.)
                frame_scrolled = True
            pickup = (confirmed_pickup(detected_info, info, target)
                      if kind == "move" else None)
            if pickup:
                collected[pickup] += 1
                frame_picked = True

            # Never batch through an attack or a pickup animation.
            first_has_item = is_pickup(info[target])
            if (kind == "move" and not approaching_wall and not first_has_item
                    and done + 1 < args.steps):
                remaining = min(effective_batch_size - 1, args.steps - done - 1)
                remaining = explore_followup_budget(reason, direction, remaining)
                if loop_guard:
                    remaining = 0
                followups = safe_followup_moves(
                    info, player, target, direction, remaining, item_goals)
                for screen_target, checked in followups:
                    if (not lawful_tap(screen_target)
                            or unsafe_move_tap(info, checked, suspect_items,
                                               remembered_items)):
                        break
                    time.sleep(delay_stretch * action_delay(
                        "move",
                        scrolled=(direction == "right"
                                  and screen_target[1] >= 2)))
                    x2, y2 = cell_tap_point(det.board, screen_target,
                                            tap_jitter)
                    bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x2), str(y2))
                    sent.append({"type": "move", "target_cell": list(screen_target),
                                 "direction": direction,
                                 "validated_from_cell": list(checked), "adb_xy": [x2, y2]})
                    expected_player = expected_after_move(screen_target, direction)
                    remembered_items.pop(tuple(screen_target), None)
                    remembered_items.pop(tuple(checked), None)
                    if direction == "right" and screen_target[1] >= 2:
                        frame_scrolled = True
                    pickup = item_category(info[checked])
                    if pickup:
                        collected[pickup] += 1
                        frame_picked = True

        event["action"] = sent
        event["collected_detected"] = dict(collected)
        wait_frames += log_frame(log, event)
        # The taps now wait for their receipt: the belt, the player's cell
        # and any refusal are all settled at the top of the next frame by
        # what the game actually charged.
        pending_taps = sent
        pending_picked = frame_picked
        if sent:
            idle_frames = 0
        done += len(sent)
        if args.verbose:
            progress(done, args.steps, f"{len(sent)} acción(es) ejecutadas - nuevo escaneo", "32")
        elif progress_step and (done >= next_progress or done >= args.steps):
            elapsed = time.monotonic() - started_at
            progress(done, args.steps, progress_summary(done, args.steps, elapsed), "32")
            while next_progress <= done:
                next_progress += progress_step
        previous_action = kind
        last_single_move = (kind == "move" and len(sent) == 1)
        previous_attack_target = target if kind == "attack" else None
        if kind == "dash":
            previous_dash_player = player
            previous_dash_obstacles = consecutive_right_obstacles(info, player)
        previous_direction = direction
        # A veto the cost guard overruled twice is a loop, not a
        # saving: the next decision may buy its way out.
        overrule_streak = next_overrule_streak(overrule_streak,
                                               blocked_direction, direction)
        previous_reason = reason
        lag_cooldown = max(0, lag_cooldown - 1)
        time.sleep(delay_stretch
                   * action_delay(kind,
                                  scrolled=frame_scrolled or kind == "dash",
                                  picked_up=frame_picked))

    final = bot.screenshot(args.adb, args.serial)
    final_det = bot.classify(final)
    keep_evidence(run_dir, "final.png", final)
    keep_evidence(run_dir, "final_diagnostic.png",
                  bot.diagnostic(final, final_det))
    event = {"time_utc": datetime.now(timezone.utc).isoformat(),
             "status": "out_of_steps" if stamina_exhausted else "complete",
             "steps": done, "run_dir": str(run_dir) if run_dir else None,
             "detection": bot.asdict(final_det)}
    energy_end, energy_end_source = final_energy(
        lambda: read_energy_counter(
            bot.screenshot(args.adb, args.serial),
            run_dir / "energy_roi_end.png" if run_dir else None),
        last_loop_energy)
    event["inventory_hud"] = {"start": inventory_start,
                              "end": read_drop_counters(final)}
    event["collected_detected"] = dict(collected)
    event["energy_hud"] = {
        "start": energy_start,
        "end": energy_end,
        "difference": (energy_end - energy_start
                       if energy_start is not None and energy_end is not None else None),
        "end_source": energy_end_source,
    }
    event["efficiency"] = efficiency_report(
        taps_claimed, taps_charged, wait_frames, frames_seen,
        time.monotonic() - started_at,
        event["energy_hud"]["difference"])
    event["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    wait_frames += log_frame(log, event)
    show_run_summary(done, args.steps, started_at, collected, energy_start, energy_end)
    progress(done, args.steps, format_efficiency(event["efficiency"]), "36")
    return 8 if idle_abort else 7 if stamina_exhausted else 0


if __name__ == "__main__":
    raise SystemExit(main())
