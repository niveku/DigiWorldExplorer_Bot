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
    if not str(reason).startswith("explore"):
        return False
    return not (set(item_goals) - set(suspect_items))


def _left_band_suspects(suspect_cells):
    # A runner-forced dash scrolls three columns and deletes left-band
    # suspects before their one-frame adjudication, exactly like the
    # strategy-side dash rules it overrides; both overrides defer to them.
    return any(cell[1] <= 2 for cell in suspect_cells)


def corridor_dash_due(action, last_attack, done, preview, dashes_enabled, ttl=4,
                      suspect_cells=()):
    """Second garra on the same row with another pyramid incoming: dash.

    Run 20260820T025148 events 84-87 spent two garras (400 shards) plus four
    actions breaking pyramids that scrolled one after another into row 3. A
    dash costs the same 400, breaks up to three, and advances three cells -
    strictly better once the row is a corridor. The sixth-column preview
    provides the 'another one is coming' evidence.
    """
    if not dashes_enabled or action is None or action[0] != "attack":
        return False
    if preview is None or last_attack is None:
        return False
    if _left_band_suspects(suspect_cells):
        return False
    row = action[1][0]
    return (last_attack[0] == row and done - last_attack[1] <= ttl
            and bool(preview[row]))


# Net burn per executed action, measured across 13 runs / 2,750 actions
# (refunds from claw/orb/paw pickups already netted out): 2,144 steps,
# 91 garras, 73 dashes. Ratio ~24 steps : 1 garra : 0.8 dashes.
BURN_PER_ACTION = {"steps": 0.78, "attacks": 0.033, "dashes": 0.027}
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


def suspect_appearances(current, previous, shift=0, attack_cell=None,
                        revealed_cells=()):
    """Item cells that appeared where nothing can appear.

    Game invariants (user-confirmed 2026-08-21): items only enter the
    board from the right edge, or revealed at a cell whose pyramid was
    just broken - by a garra (attack_cell) or by a dash (revealed_cells,
    the dash path shifted by its own 3-column scroll). Any other arrival
    is animation residue - the +20 confetti painted 6-9 phantom oranges
    per pickup (run 20260820T183527). Suspects are ignored as targets
    for one frame; a real item survives into the next frame's
    previous-set and stops being suspect. The caller always counts the
    scroll exactly (the old guess-the-shift fallback hid ghost 105 of
    run 20260820T184744 behind a coincidental mapping).
    """
    if not previous:
        return set()
    shifted = {(row, col - shift) for row, col in previous}
    fresh = set(current) - shifted
    legit = {tuple(cell) for cell in revealed_cells}
    if attack_cell:
        legit.add(tuple(attack_cell))
    return {cell for cell in fresh if cell[1] < 4 and cell not in legit}


def combined_suspects(fresh, previous_fresh, current):
    """Suspects for this frame: fresh arrivals plus last frame's fresh
    arrivals that are still visible.

    The pickup confetti spans two frames (it starts on the pickup frame
    itself, run 20260820T184744 event 136), so a 1-frame check saw the
    second frame as a survivor. Carrying over only the FRESH set caps
    the suspicion at two frames: a real item unlocks on frame three.
    """
    return set(fresh) | (set(previous_fresh) & set(current))


def prune_remembered_items(remembered, done, player, ttl=25):
    """Drop remembered pickups that expired or were just visited.

    Game invariant (user, 2026-08-21): no pickup - claws included - ever
    vanishes except by collection or the left edge, so the old
    claw-specific 4-frame TTL only recreated the flicker churn the
    memory exists to prevent. One unified TTL guards against our own
    coordinate errors; collection pops and the scroll shift handle the
    legitimate exits.
    """
    return {cell: value for cell, value in remembered.items()
            if done - value[1] <= ttl and cell != player}


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
    15-20% of the frame height and red-framed advice sections below it;
    when it pops because the stage ended, a big red 'Stage Failed'
    headline sits in the top band. On the fixture: 75 gray title rows
    (floor 2% of height), red-frame density 0.0022 (floor 0.001), red
    headline density 0.0101 (floor 0.003); nine board fixtures score
    at most a fifth of each floor. One numpy pass, no OCR."""
    a = np.asarray(image.convert("RGB")).astype(int)
    height, width = a.shape[:2]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gray = ((np.abs(r - g) < 18) & (np.abs(g - b) < 18)
            & (r > 120) & (r < 190))
    title_rows = gray[int(height * .10):int(height * .30)].mean(axis=1)
    red_frames = ((r > 150) & (g < 60) & (b < 70))[int(height * .20):
                                                   int(height * .85)]
    if (int((title_rows > .15).sum()) < int(height * .02)
            or red_frames.mean() < .001):
        return None
    headline = ((r > 190) & (g < 70) & (b < 80))[:int(height * .13)]
    return {"stage_failed": bool(headline.mean() > .003)}


def dismiss_tap_due(unreliable):
    """Tap outside a suspected popup on the 2nd and 4th unreliable strike.

    Run 20260821T173052: the Stage Failed "Growth Guide" panel covered the
    board and the run died after five unreliable-board waits with the
    panel still open. One tap outside its frame closes it (user
    confirmed), so two attempts fit before the 5-strike stop."""
    return unreliable in (2, 4)


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


def should_hold_for_adjacent_suspect(player, suspect_items, reason, action,
                                     holds, max_holds=2):
    """A suspect ONE step away decides the plan either way: wait for it.

    Run 20260822T162851 n=49-50: the steps card at (4,2) was suspect,
    so the tour left it out and stepped UP toward a far orange; the
    card confirmed on the very next frame and the tour walked right
    back down. Any plain move with an orthogonally adjacent suspect
    waits (an adjacent grab of something REAL is exempt - it loses
    nothing either way); two holds cover the adjudication window."""
    if holds >= max_holds or action is None or action[0] != "move":
        return False
    if str(reason).startswith("adjacent item"):
        return False
    return any(abs(cell[0] - player[0]) + abs(cell[1] - player[1]) == 1
               for cell in suspect_items)


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
    if _left_band_suspects(suspect_cells):
        return False
    if left_band_risk:
        # Same deference as the strategy-side wall rule: the dash's
        # scroll deletes left-band pickups. Run 20260822T162851 n=52
        # fired this override with a remembered orange at (0,1) and
        # scrolled it off the board.
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


def shift_pickup_log_left(recent_pickups):
    """Scroll compensation for the burst-zone pickup log."""
    return [((row, col - 1), when)
            for (row, col), when in recent_pickups if col - 1 >= 0]


def shift_items_right(remembered):
    """Undo one over-counted scroll: the world moved LESS than the taps
    claimed, so every shifted structure steps one column back right.
    Cells pushed past the right edge are dropped (nothing legitimate
    lives there that memory needs to resurrect)."""
    return {(row, col + 1): value
            for (row, col), value in remembered.items() if col + 1 <= 4}


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
    for off in range(0, max_off + 1, 2):
        a = prev_strip[:, off:]
        b = cur_strip[:, :width - off]
        score = float(np.mean(np.abs(a - b)))
        if best_score is None or score < best_score:
            best_off, best_score = off, score
    cols_f = best_off / col_px
    nearest = int(round(cols_f))
    sliding = abs(cols_f - nearest) > slide_tolerance
    return min(nearest, max_cols), sliding


def scroll_shortfall_wait(measured, claimed, waits, max_waits=1):
    """Give a late scroll one extra frame before reconciling.

    A tap's scroll often lands AFTER the next screenshot: the sensor
    reads short, and reconciling immediately unshifts memory that the
    late scroll then re-desyncs (run 20260822T171206 n=91-95, five
    'swallowed' taps in a row that were merely late). One held frame
    lets the animation land; a shortfall that persists is a genuinely
    swallowed tap and reconciles."""
    if measured is None or measured >= claimed:
        return False
    return waits < max_waits


def pointless_attack(detected_info, target):
    """A garra may only go to a cell DETECTION shows as a pyramid.

    Run 20260822T171206 n=163: a cannot-move toast minted a phantom
    obstacle, the router attacked it - 200 shards swung at an empty
    cell - and then walked an 8-step detour around a wall that did not
    exist. A phantom vision cannot confirm gets dropped, not hit."""
    return not strategy.is_obstacle(detected_info[tuple(target)])


def sticky_left_band_suspects(prev_suspects, current_cells, ages, band=2,
                              ttl=4):
    """An unexplained left-band appearance is not believed - for a TTL.

    Doctrine 2026-08-22 (user): columns 0-2 are KNOWN world - nothing
    new can exist there except a garra drop (whitelisted) or what
    memory already tracks, so an unexplained appearance is confetti by
    definition and stays suspect while visible. But only for ttl
    frames: run 20260822T165752 n=12-17 (user force-stop) flagged a
    REAL orange once during phantom-tap chaos and the un-expiring
    version blind-sided the bot against an energy sitting in front of
    it. Confetti never survives 4 settled frames (measured over the
    2026-08-22 runs); anything that does is real and gets released.
    Returns (held_cells, updated_ages)."""
    held = set()
    new_ages = {}
    for cell in prev_suspects:
        if cell not in current_cells or cell[1] > band:
            continue
        age = ages.get(cell, 0) + 1
        if age < ttl:
            held.add(cell)
            new_ages[cell] = age
    return held, new_ages


RESCAN_DELAY = 0.5

ACTION_DELAYS = {
    "move": 0.35,
    "move_scroll": 0.60,
    "move_pickup": 0.65,
    "move_pickup_scroll": 0.80,
    "attack": 0.90,
    "dash": 1.40,
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


def silent_rejection(previous_action, expected_rollback, player,
                     first_move_dest, player_source, player_score):
    """The game refused the last move - detected by position, not pixels.

    'Cannot move there' toasts are invisible since the confetti gate
    (they do not degrade board detection; run 20260821T222310 n=124/129
    had two such stuck frames with nothing in the log). A confidently
    seen player still standing on the pre-move cell after a NON-SCROLL
    move proves the tap was refused. Scroll rides prove nothing: riding
    right leaves the player on the same screen cell by design."""
    if previous_action != "move" or expected_rollback is None:
        return False
    if first_move_dest is None or first_move_dest == expected_rollback:
        return False
    if player != expected_rollback:
        return False
    return player_source == "vision" and player_score >= .12


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
            values["item"] = 0.0
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
        "remembered": {f"{r},{c}": cat
                       for (r, c), (cat, _) in remembered.items()},
    }


def remember_confirmed_items(remembered, info, player, suspects, done):
    """Record every confirmed pickup sighting; a pickup cannot vanish.

    It leaves the board by collection or by the left edge, nothing else
    (game physics, user-confirmed). Run 20260821T192126 lost eleven
    confirmed pickups to the left edge because each flickered one frame
    under a pickup animation and re-entered as a fresh suspect forever.
    Memory recorded from PRE-merge detections (so a remembered ghost can
    never refresh itself through its own merged patch) bridges the
    flicker: the cell stays visible to the pathfinder and never reads as
    a fresh arrival again. Suspects are not recorded - confetti phantoms
    live shorter than the two-frame adjudication."""
    updated = dict(remembered)
    for cell, values in info.items():
        if cell == player or cell in suspects:
            continue
        if not is_pickup(values):
            continue
        category = item_category(values)
        if category is not None:
            updated[cell] = (category, done)
    return updated


def drop_remembered_suspects(suspects, remembered):
    """Memory outranks suspicion: a remembered cell cannot be a suspect.

    Run 20260821T213642 n=51-56: the dash orb at (4,0) sat in memory
    (confirmed) and in the suspect set (its detection flickered into a
    'fresh arrival' every other frame) at the same time. Suspects feed
    choose() as ignored targets, so the confirmed orb was never targeted
    and scrolled off the board."""
    return {cell for cell in suspects if cell not in remembered}


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


def drop_shift_ghosts(remembered, info):
    """Kill memory twins created by an over-counted scroll.

    Run 20260821T225908 n=13-14 (user-confirmed: ONE claw on screen, two
    in memory): a scroll tap the game swallowed still counted in the
    shift accounting, so memory slid the claw one column left while the
    live detection re-recorded it in place - and after grabbing the real
    one the bot stepped left into the ghost. A remembered cell that is
    NOT detected while its right neighbor holds a live detection of the
    same category is such a ghost and dies."""
    def detected_category(cell):
        values = info.get(cell)
        if values is None or not is_pickup(values):
            return None
        return item_category(values)

    return {cell: value for cell, value in remembered.items()
            if not (detected_category(cell) is None
                    and detected_category((cell[0], cell[1] + 1)) == value[0])}


def remember_revealed_pickup(remembered, pyramid_result, cell, done):
    """A pickup revealed by a broken pyramid enters memory immediately.

    The reveal animation can hide the drop from the very next frame's
    detector (user report 2026-08-21: broke a pyramid, walked to the
    middle cell, only then saw the energy and walked back). The attack
    result already names the revealed category, so the cell becomes a
    remembered goal before the detector ever needs to see it."""
    revealed = (pyramid_result or {}).get("revealed")
    if not revealed or not (pyramid_result or {}).get("broken"):
        return remembered
    updated = dict(remembered)
    updated[tuple(cell)] = (revealed, done)
    return updated


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


def player_cell(info):
    return max(((p, v["player"]) for p, v in info.items()), key=lambda q: q[1])


def adaptive_batch_limit(requested, item_goals):
    """Allow three clicks only for Batch-2 frames without visible pickups."""
    return 3 if requested == 2 and not item_goals else requested


def is_pickup(values):
    """Any collectible cell: color-mask items or the yellow claw.

    The claw scores low on the color "item" mask (it has its own mask), so
    checking only values["item"] left claw-only boards looking item-free:
    batches grew to 3 moves and overshot the turn cell toward the claw."""
    return values["item"] > .06 or values.get("claw", 0.0) > .10


def pickup_goals(info, player):
    """All collectible cells except the player's own."""
    return {cell for cell, values in info.items()
            if is_pickup(values) and cell != player}


def is_single_step_approach(reason):
    """Dash approaches advance one verified cell per screenshot.

    Blind follow-ups batched past the launch row on both approach kinds
    (wall approach, and "pair launch" in run 20260820T180814 events 33-35,
    which ping-ponged around row 3 instead of launching)."""
    return reason.startswith(("approach dash wall", "pair launch"))


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


def unsafe_move_tap(info, target, suspects=()):
    """A 'move' tap onto a pyramid or a suspect cell must not go out.

    A tap onto a cell the game shows as a pyramid EXECUTES a garra.
    HUD counter audit (run 20260822T142042): the attack counter
    dropped ~7 more times than the log sent attacks - every one a move
    tap landing on a pyramid the planner did not see. The guards cut
    that to one hidden garra the very next run (20260822T160202): the
    survivor at n=89 stepped onto the SUSPECT cell (1,1) - confetti
    covering a pyramid the vision could not see. A suspect cell is
    unknown ground: never tap it, wait for adjudication."""
    return (strategy.is_obstacle(info[tuple(target)])
            or tuple(target) in suspects)


def burst_holds(prev_fresh, current_cells, recent_pickups, done,
                radius=2, ttl=3):
    """Confetti-zone survivors need one extra frame of belief.

    Confetti only exists around a fresh pickup, and its cards can
    survive the standard two sightings (run 20260822T160202 n=36-38:
    the SKIP frame donated one, and the bot walked to an empty cell).
    A fresh appearance from the PREVIOUS frame that sits within radius
    cells of a pickup made in the last ttl frames stays suspect for
    one more frame; real items are untouched - nothing legitimately
    appears mid-board except garra drops (whitelisted) and right-edge
    arrivals (outside any burst zone by the time they matter)."""
    zones = [cell for cell, when in recent_pickups if done - when < ttl]
    return {cell for cell in prev_fresh
            if cell in current_cells
            and any(abs(cell[0] - z[0]) <= radius
                    and abs(cell[1] - z[1]) <= radius for z in zones)}


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
    previous_distance = (min(abs(first_target[0]-g[0]) + abs(first_target[1]-g[1])
                             for g in goals) if goals else None)
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
        if goals:
            distance = min(abs(checked_cell[0]-g[0]) + abs(checked_cell[1]-g[1])
                           for g in goals)
            # Strictly closer, not merely no-worse: with several goals a
            # move can trade distance-to-A for distance-to-B and keep the
            # min flat while overshooting the route's turn cell (run
            # 20260821T200525 n=353-359 ping-ponged six moves that way).
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
    p.add_argument("--debug-screenshots", action="store_true")
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
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 10

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
    inventory_start = None
    pending_attack_inv = None
    expected_player = None
    expected_rollback = None
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
    total_scrolls = 0
    prev_fresh_suspects = set()
    prev_suspect_items = set()
    sticky_ages = {}
    prev_strip = None
    scroll_waits = 0
    lag_cooldown = 0
    recent_pickups = []
    committed_wall = None
    wall_holds = 0
    last_dash = None
    chest_cooldown = 0
    prev_item_cells = None
    last_attack = None
    previous_action = None
    previous_attack_target = None
    previous_dash_player = None
    previous_dash_obstacles = 0
    pending_dash = None
    previous_direction = None
    previous_reason = None
    suspect_holds = 0
    stable_board = None
    unreliable = 0
    player_unreliable = 0
    overlay_waits = 0
    overlay_evidence_saved = 0
    phantom_obstacles = {}
    pending_reveals = {}
    settle_waits = 0
    no_action_waits = 0
    attack_noeffect_streak = 0
    first_move_dest = None
    last_stamina_check = 0
    last_move_player_source = None
    last_move_player_score = 0.0
    distrust_player = False
    rejected_streak = 0
    recent_states = []

    while done < args.steps:
        image = bot.screenshot(args.adb, args.serial)
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
                bot.log_event(log, event)
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
                        bot.log_event(log, event)
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
                        try:
                            evidence_path = run_dir / "rejected_moves_evidence.png"
                            image.save(evidence_path)
                            event["evidence"] = str(evidence_path)
                        except OSError:
                            pass
                        bot.log_event(log, event)
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
                    try:
                        evidence_path = (run_dir /
                                         f"overlay_evidence_{done:04d}.png")
                        bot.diagnostic(image, det).save(evidence_path)
                        event["evidence"] = str(evidence_path)
                        overlay_evidence_saved += 1
                    except OSError:
                        pass
                if overlay_waits >= 15:
                    # A persistent overlay (e.g. an unclaimed milestone popup)
                    # would otherwise hang the run silently forever.
                    event["action"] = "STOP: persistent overlay"
                    try:
                        evidence_path = run_dir / "overlay_stop_evidence.png"
                        image.save(evidence_path)
                        event["evidence"] = str(evidence_path)
                    except OSError:
                        pass
                    bot.log_event(log, event)
                    show_run_summary(done, args.steps, started_at, collected,
                                     energy_start, read_energy_counter(image), "33")
                    return 5
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, str(event["action"]), "33")
            time.sleep(RESCAN_DELAY); continue

        overlay_waits = 0
        # (Rejection accounting moved below the player resolution: toasts
        # are invisible to detection since the confetti gate, so a refused
        # move is recognized by the player standing still instead.)
        if det.state != "digiworld" or not det.board or det.confidence < args.min_confidence:
            unreliable += 1
            event["action"] = f"WAIT: unreliable board ({unreliable}/5)"
            # A recognized Growth Guide panel is dismissed on every strike
            # and logged with its stage_failed flag; an unrecognized cover
            # still gets the blind outside-tap on strikes 2 and 4.
            panel = growth_guide_overlay(image)
            if panel is not None:
                event["overlay"] = dict(panel, kind="growth_guide")
            if panel is not None or dismiss_tap_due(unreliable):
                bot.adb(args.adb, args.serial, "shell", "input", "tap",
                        str(DISMISS_TAP_XY[0]), str(DISMISS_TAP_XY[1]))
                event["dismiss_tap"] = list(DISMISS_TAP_XY)
                if args.verbose:
                    label = ("Panel Growth Guide detectado - cerrando"
                             if panel is not None else
                             "Popup sospechado - tap fuera del panel")
                    if panel is not None and panel.get("stage_failed"):
                        label = ("Stage Failed + Growth Guide - cerrando "
                                 "para continuar")
                    progress(done, args.steps, label, "33")
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "Tablero inestable - nuevo escaneo", "33")
            if unreliable >= 5:
                show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
                return 2
            time.sleep(RESCAN_DELAY); continue
        unreliable = 0
        # The out-of-steps STOP used to live only behind the modal-overlay
        # path; with the confetti gate that path fires rarely, so the
        # stamina counter is polled directly every 25 actions instead.
        if done - last_stamina_check >= 25:
            last_stamina_check = done
            if out_of_steps(read_inventory_counters(image), rejected_streak=2):
                event["action"] = "STOP: out of steps (stamina 0)"
                bot.log_event(log, event)
                print("Pasos agotados: el contador de estamina marca 0. "
                      "Se regeneran por debajo de 100, o se compran con "
                      "shards (2000 = 50 pasos).")
                show_run_summary(done, args.steps, started_at, collected,
                                 energy_start, read_energy_counter(image), "33")
                return 7
        if energy_start is None:
            current_read = read_energy_counter(image, run_dir / "energy_roi_start.png")
            energy_start = confirmed_energy(last_energy_read, current_read)
            last_energy_read = current_read
            if args.verbose and energy_start is not None:
                progress(done, args.steps, f"Energía inicial: {format_counter(energy_start)}", "93")
        if inventory_start is None:
            reading = read_drop_counters(image)
            if any(value is not None for value in reading.values()):
                inventory_start = reading
                event["inventory_start"] = reading
                # Shopping advice for the whole planned run, from measured
                # burn rates - printed once, before spending anything.
                recommendation = purchase_recommendation(
                    args.steps - done, reading)
                event["purchase_recommendation"] = recommendation
                print(format_purchase_advice(recommendation))

        # Per-frame energy timeline: makes milestone rewards (+1000 spikes)
        # distinguishable from gradual per-meter accrual in the log.
        event["energy"] = read_energy_counter(image)

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
                bot.log_event(log, event)
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
        distrust_player = False
        if silent_rejection(previous_action, expected_rollback, player,
                            first_move_dest, player_source, player_score):
            rejected_streak += 1
            phantom_obstacles[first_move_dest] = done + 6
            event["silent_rejection"] = {"stuck_at": list(player),
                                         "refused": list(first_move_dest),
                                         "streak": rejected_streak}
            expected_player = player
            if args.verbose:
                progress(done, args.steps,
                         f"Movimiento rechazado hacia {list(first_move_dest)} "
                         "- celda marcada como bloqueada", "33")
        elif previous_action == "move" and expected_rollback is not None:
            rejected_streak = 0
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
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "Posición del jugador insegura - nuevo escaneo", "33")
            if player_unreliable >= 5:
                event["action"] = "STOP: five consecutive unreliable player frames"
                try:
                    evidence_path = run_dir / "player_stop_evidence.png"
                    bot.diagnostic(image, det).save(evidence_path)
                    event["evidence"] = str(evidence_path)
                except OSError:
                    pass
                bot.log_event(log, event)
                show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
                return 3
            time.sleep(1.0); continue
        player_unreliable = 0
        if player_source == "large-sprite":
            # A big sprite's own colors read as pickups in the cells its body
            # covers; wipe them so the bot stops chasing its own wings. Items
            # sighted from afar are remembered so getting close (and wiping
            # their cell) does not make the goal flicker away.
            info = strategy.suppress_sprite_leaks(info, player)
            for cell, values in info.items():
                if values["item"] > .06 and cell != player:
                    remembered_items[cell] = (item_category(values) or "orange", done)
        # (The separate claw-sighting loop retired 2026-08-21: claws are
        # ordinary confirmed pickups now - remember_confirmed_items
        # records them with the same suspect gating as everything else.)
        remembered_items = prune_remembered_items(remembered_items, done, player)
        # Memory is recorded from this pre-merge snapshot further down, so
        # a remembered cell can never refresh its own timestamp through
        # the just-over-threshold patch the merge injects.
        detected_info = info
        # Scroll reconciliation BEFORE the memory merge, by MEASURING
        # the world instead of trusting the tap count (user doctrine
        # 2026-08-22: 'confirmar que se movió y ya reconciliar'). The
        # board strip of consecutive settled frames is aligned at
        # shifts 0..3 columns; whatever the taps claimed, the argmin IS
        # the scroll. This replaced the cell-fingerprint heuristic and
        # closes every swallowed/duplicated-tap ghost in one place
        # (run 20260822T164337 n=30-32: two hidden garras, HUD 41->39,
        # from memory running one column ahead of a latency-swallowed
        # tap).
        cur_strip = board_strip(image, det.board)
        measured, board_sliding = measure_scroll_px(prev_strip, cur_strip,
                                                    max_cols=2)
        # Three strip columns verify shifts up to 2; a dash's 3-column
        # jump is out of range and the tap count is trusted (the dash
        # has its own long animation and settle wait).
        measurable = scrolls_since_frame <= 2
        if board_sliding:
            # The grid stands still while its CONTENTS slide: this
            # screenshot caught the scroll in flight. Acting on it
            # desynced memory 17 times in run 20260822T171206.
            event["action"] = "WAIT: board content sliding"
            bot.log_event(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Contenido del tablero en movimiento - espero", "33")
            time.sleep(0.6)
            continue
        if measurable and scroll_shortfall_wait(measured, scrolls_since_frame,
                                                scroll_waits):
            scroll_waits += 1
            event["action"] = (f"WAIT: scroll shortfall measured={measured} "
                               f"claimed={scrolls_since_frame} ({scroll_waits}/1)")
            bot.log_event(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Scroll aún no aterriza - espero un frame", "33")
            time.sleep(0.7)
            continue
        scroll_waits = 0
        prev_strip = cur_strip
        if (measurable and measured is not None
                and measured != scrolls_since_frame):
            delta = scrolls_since_frame - measured
            step_right = delta > 0
            for _ in range(abs(delta)):
                shifter = shift_items_right if step_right else shift_items_left
                remembered_items = shifter(remembered_items)
                phantom_obstacles = shifter(phantom_obstacles)
                banned_targets = shifter(banned_targets)
                pending_reveals = shifter(pending_reveals)
                if step_right:
                    ban_history = {(r, c + 1) for r, c in ban_history
                                   if c + 1 <= 4}
                    recent_pickups = [((r, c + 1), w) for (r, c), w
                                      in recent_pickups if c + 1 <= 4]
                else:
                    ban_history = shift_cells_left(ban_history)
                    recent_pickups = shift_pickup_log_left(recent_pickups)
            event["scroll_reconciled"] = {"claimed": scrolls_since_frame,
                                          "measured": measured}
            if measured < scrolls_since_frame:
                # The game swallowed taps: it is lagging. Single steps
                # for the next two decisions instead of feeding batches
                # into the freeze.
                lag_cooldown = 2
            scrolls_since_frame = measured
        if remembered_items:
            info = merge_remembered_items(info, remembered_items, player)
        phantom_obstacles = {cell: expiry
                             for cell, expiry in phantom_obstacles.items()
                             if expiry > done}
        info = merge_phantom_obstacles(info, phantom_obstacles, done)
        current_item_cells = item_cells_of(info)
        # Mid-board arrivals that neither the scroll nor a garra-broken
        # pyramid explains are confetti: ignored as targets for one frame
        # instead of waiting. Only garra target cells stay whitelisted
        # for a few frames via pending_reveals - the fall animation can
        # delay the drop's detection past the break frame. Dashes leave
        # no drops (they collect what they break), so they get no window.
        pending_reveals = {cell: expiry
                           for cell, expiry in pending_reveals.items()
                           if expiry > done}
        fresh_suspects = suspect_appearances(
            current_item_cells, prev_item_cells,
            shift=scrolls_since_frame,
            attack_cell=(previous_attack_target
                         if previous_action == "attack" else None),
            revealed_cells=live_reveal_cells(pending_reveals, done))
        suspect_items = combined_suspects(fresh_suspects, prev_fresh_suspects,
                                          current_item_cells)
        suspect_items = drop_remembered_suspects(suspect_items, remembered_items)
        suspect_items |= burst_holds(prev_fresh_suspects, current_item_cells,
                                     recent_pickups, done)
        # Known-world doctrine (user 2026-08-22): an unexplained
        # left-band appearance can only be confetti, so it is never
        # promoted - it stays suspect for as long as it stays visible.
        shifted_prev_susp = {(r, c - scrolls_since_frame)
                             for r, c in prev_suspect_items
                             if c - scrolls_since_frame >= 0}
        shifted_ages = {(r, c - scrolls_since_frame): v
                        for (r, c), v in sticky_ages.items()
                        if c - scrolls_since_frame >= 0}
        held, sticky_ages = sticky_left_band_suspects(shifted_prev_susp,
                                                      current_item_cells,
                                                      shifted_ages)
        suspect_items |= held
        suspect_items = drop_remembered_suspects(suspect_items,
                                                 remembered_items)
        prev_suspect_items = set(suspect_items)
        prev_fresh_suspects = fresh_suspects
        prev_item_cells = current_item_cells
        total_scrolls += scrolls_since_frame
        scrolls_since_frame = 0
        remembered_items = remember_confirmed_items(
            remembered_items, detected_info, player, suspect_items, done)
        remembered_items = drop_shift_ghosts(remembered_items, detected_info)
        # Detection-only: logging the merged board painted remembered
        # ghosts as real items and a forensic pass adjudicated the
        # debug_0124 ghost walk as a "real orange rescue" against the
        # user's own eyes (2026-08-22). Memory travels separately in
        # "remembered"; "items" is what the screen actually showed.
        event["board"] = compact_state(detected_info, player, remembered_items)
        if suspect_items:
            event["suspect_items"] = sorted(list(cell) for cell in suspect_items)
        preview = strategy.sixth_column_preview(image, det.board)
        if preview is not None and any(preview):
            event["sixth_column"] = preview
        item_goals = pickup_goals(info, player)
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
            remembered_items = remember_revealed_pickup(
                remembered_items, result, previous_attack_target, done)
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
                try:
                    evidence_path = run_dir / f"phantom_attack_{done:04d}.png"
                    bot.diagnostic(image, det).save(evidence_path)
                    event["attack_state"]["evidence"] = str(evidence_path)
                except OSError:
                    pass
            previous_attack_target = None
        if previous_action == "dash" and previous_dash_player is not None:
            if pending_dash is not None:
                after_dump = (run_dir / f"energy_roi_dash_{done:04d}_after.png"
                              if args.debug_screenshots else None)
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
                pending_dash = None
            current_right_obstacles = consecutive_right_obstacles(info, player)
            if (player == previous_dash_player and
                    previous_dash_obstacles >= 2 and current_right_obstacles >= 2):
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
        action, reason = strategy.choose(info, previous_direction,
                                         attacks_enabled, dashes_enabled,
                                         ignored_targets=(set(banned_targets.keys())
                                                          | suspect_items),
                                         player=player, preview=preview,
                                         hunt_walls=wall_stable,
                                         suspect_cells=suspect_items)
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
                             suspect_cells=suspect_items):
            action, reason = ("dash", player, "right"), "corridor dash"
        if (dashes_enabled and should_hold_for_wall(wall_now, wall_stable,
                                                    action, reason,
                                                    wall_holds)):
            wall_holds += 1
            event["reason"] = reason
            event["action"] = (f"WAIT: wall at {list(wall_now)} stabilizing "
                               f"({wall_holds}/2)")
            bot.log_event(log, event)
            if args.verbose:
                progress(done, args.steps,
                         "Muro a la vista sin confirmar - espero un frame", "33")
            time.sleep(.4)
            continue
        wall_holds = 0
        if (should_hold_for_suspects(reason, item_goals, suspect_items,
                                     suspect_holds)
                or should_hold_for_adjacent_suspect(player, suspect_items,
                                                    reason, action,
                                                    suspect_holds)):
            suspect_holds += 1
            event["reason"] = reason
            event["action"] = ("WAIT: suspects pending confirmation "
                               f"{sorted(list(c) for c in suspect_items)}")
            bot.log_event(log, event)
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
                                             suspect_cells=suspect_items)
        if action is None:
            # One unreadable frame must not kill a run: rescan a few
            # times before giving up.
            no_action_waits += 1
            if no_action_waits < 3:
                event["action"] = f"WAIT: no safe action ({no_action_waits}/3)"
                bot.log_event(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             "Sin acción segura - nuevo escaneo", "33")
                time.sleep(.4)
                continue
            event["action"] = "STOP: no safe action"
            bot.log_event(log, event)
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
        if args.debug_screenshots:
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
            debug_path = run_dir / f"debug_{done:04d}_{safe_stamp}.png"
            debug.save(debug_path)
            event["debug"] = str(debug_path)

        if kind == "dash":
            control = bot.dash_button(image)
            if control is None:
                dashes_enabled = False
                dashes_disabled_at = done
                event["action"] = "WAIT: dash button missing"
                bot.log_event(log, event)
                if args.verbose: progress(done, args.steps, "Dash no disponible - replanificando", "33")
                continue
            dash_path = dash_path_report(info, player)
            event["dash_path"] = dash_path
            dash_dump = (run_dir / f"energy_roi_dash_{done:04d}_before.png"
                         if args.debug_screenshots else None)
            pending_dash = {"path": dash_path,
                            "energy_before": read_energy_counter(image, dash_dump)}
            pending_dash["inventory_before"] = read_drop_counters(image)
            bot.adb(args.adb, args.serial, "shell", "input", "tap",
                    str(control[0]), str(control[1]))
            sent.append({"type": "dash", "adb_xy": list(control)})
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
                recent_pickups = shift_pickup_log_left(recent_pickups)
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
                bot.log_event(log, event)
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
                event["action"] = f"SKIP: garra at visually empty {list(target)}"
                bot.log_event(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             f"Garra a celda vacía {list(target)} suprimida - "
                             "replanificando", "33")
                time.sleep(RESCAN_DELAY)
                continue
            if kind == "move" and unsafe_move_tap(info, target, suspect_items):
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
                bot.log_event(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             f"Tap sobre {note} en {list(target)} suprimido - "
                             "replanificando", "33")
                time.sleep(RESCAN_DELAY)
                continue
            x, y = bot.cell_center(det.board, *target)
            if kind == "attack":
                pending_attack_inv = read_drop_counters(image)
                last_attack = (target[0], done)
                pending_reveals = remember_pending_reveals(
                    pending_reveals, [target], done)
            bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
            sent.append({"type": kind, "target_cell": list(target), "adb_xy": [x, y]})
            expected_rollback = player
            expected_player = (player if kind == "attack"
                               else expected_after_move(target, direction))
            first_move_dest = (expected_after_move(target, direction)
                               if kind == "move" else None)
            last_move_player_source = player_source
            last_move_player_score = player_score
            if kind == "move":
                # Stepping onto a cell collects whatever it held: its
                # memory dies before the scroll shift below relabels it.
                remembered_items.pop(tuple(target), None)
            if kind == "move" and direction == "right" and target[1] >= 2:
                remembered_items = shift_items_left(remembered_items)
                phantom_obstacles = shift_items_left(phantom_obstacles)
                banned_targets = shift_items_left(banned_targets)
                ban_history = shift_cells_left(ban_history)
                pending_reveals = shift_items_left(pending_reveals)
                recent_pickups = shift_pickup_log_left(recent_pickups)
                # The wall commitment survives the scroll: wall_is_stable
                # carries the scroll count at sighting and adjusts the
                # expected launch column. Clearing it here made a wall
                # seen while riding rightward permanently "unstable" -
                # run 20260822T004437 n=48-49 exploring right past a
                # 3-pyramid wall one step down, never hunted.
                scrolls_since_frame += 1
            pickup = item_category(info[target]) if kind == "move" else None
            if pickup:
                collected[pickup] += 1
                recent_pickups.append((tuple(target), done))
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
                            or unsafe_move_tap(info, checked, suspect_items)):
                        break
                    time.sleep(action_delay(
                        "move",
                        scrolled=(direction == "right"
                                  and screen_target[1] >= 2)))
                    x2, y2 = bot.cell_center(det.board, *screen_target)
                    bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x2), str(y2))
                    sent.append({"type": "move", "target_cell": list(screen_target),
                                 "validated_from_cell": list(checked), "adb_xy": [x2, y2]})
                    expected_player = expected_after_move(screen_target, direction)
                    remembered_items.pop(tuple(screen_target), None)
                    remembered_items.pop(tuple(checked), None)
                    if direction == "right" and screen_target[1] >= 2:
                        remembered_items = shift_items_left(remembered_items)
                        phantom_obstacles = shift_items_left(phantom_obstacles)
                        banned_targets = shift_items_left(banned_targets)
                        ban_history = shift_cells_left(ban_history)
                        pending_reveals = shift_items_left(pending_reveals)
                        recent_pickups = shift_pickup_log_left(recent_pickups)
                        scrolls_since_frame += 1
                    pickup = item_category(info[checked])
                    if pickup:
                        collected[pickup] += 1
                        recent_pickups.append((tuple(checked), done))
                        frame_picked = True

        event["action"] = sent
        event["collected_detected"] = dict(collected)
        bot.log_event(log, event)
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
        previous_reason = reason
        lag_cooldown = max(0, lag_cooldown - 1)
        time.sleep(action_delay(kind, scrolled=scrolls_since_frame > 0,
                                picked_up=frame_picked))

    final = bot.screenshot(args.adb, args.serial)
    final_det = bot.classify(final)
    final.save(run_dir / "final.png")
    bot.diagnostic(final, final_det).save(
        run_dir / "final_diagnostic.png")
    event = {"time_utc": datetime.now(timezone.utc).isoformat(), "status": "complete",
             "steps": done, "run_dir": str(run_dir),
             "detection": bot.asdict(final_det)}
    energy_end = read_energy_counter(final, run_dir / "energy_roi_end.png")
    event["inventory_hud"] = {"start": inventory_start,
                              "end": read_drop_counters(final)}
    event["collected_detected"] = dict(collected)
    event["energy_hud"] = {
        "start": energy_start,
        "end": energy_end,
        "difference": (energy_end - energy_start
                       if energy_start is not None and energy_end is not None else None),
    }
    event["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    bot.log_event(log, event)
    show_run_summary(done, args.steps, started_at, collected, energy_start, energy_end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
