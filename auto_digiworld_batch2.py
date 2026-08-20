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


def corridor_dash_due(action, last_attack, done, preview, dashes_enabled, ttl=4):
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
    ys, xs = np.where(gold | badge)
    return int(xs.mean()), int(ys.mean()) + y0


def items_flickering(current, previous):
    """True when the item set changed in a way scroll cannot explain.

    194 of 214 WAITs across four runs (045220..055223) were the burst
    guard re-firing on plain scroll shifts. A frame is suspicious only
    when some previous item is missing without having scrolled off the
    left edge (shifts of 0-3 columns are tried; new arrivals from the
    right are normal). A genuine pickup animation removes an item
    mid-board, which no shift explains.
    """
    if not previous:
        return False
    best_missing = None
    for shift in (0, 1, 2, 3):
        shifted = {(row, col - shift) for row, col in previous}
        missing = {cell for cell in shifted if cell[1] >= 0} - set(current)
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return bool(best_missing)


def suspect_appearances(current, previous, shift=None, attack_cell=None):
    """Item cells that appeared where nothing can appear.

    Items only enter the board two ways: scrolling in from the right
    edge, or revealed at a cell whose pyramid was just broken. Any other
    arrival is animation residue - the +20 confetti painted 6-9 phantom
    oranges per pickup (run 20260820T183527) and two ghosts still leaked
    past the burst WAIT (run 20260820T184744 events 105/136). Suspects
    are ignored as targets for one frame; a real item survives into the
    next frame's previous-set and stops being suspect.
    """
    if not previous:
        return set()
    if shift is None:
        # Fallback when the caller cannot count the scroll: guess the
        # shift that explains the most cells. A wrong guess can hide a
        # ghost behind a coincidental mapping - prefer the exact count.
        best_new = None
        for guess in (0, 1, 2, 3):
            shifted = {(row, col - guess) for row, col in previous}
            new = set(current) - shifted
            if best_new is None or len(new) < len(best_new):
                best_new = new
    else:
        shifted = {(row, col - shift) for row, col in previous}
        best_new = set(current) - shifted
    legit = {tuple(attack_cell)} if attack_cell else set()
    return {cell for cell in best_new if cell[1] < 4 and cell not in legit}


def combined_suspects(fresh, previous_fresh, current):
    """Suspects for this frame: fresh arrivals plus last frame's fresh
    arrivals that are still visible.

    The pickup confetti spans two frames (it starts on the pickup frame
    itself, run 20260820T184744 event 136), so a 1-frame check saw the
    second frame as a survivor. Carrying over only the FRESH set caps
    the suspicion at two frames: a real item unlocks on frame three.
    """
    return set(fresh) | (set(previous_fresh) & set(current))


def prune_remembered_items(remembered, done, player, ttl_by_category=None):
    """Drop remembered pickups that expired or were just visited.

    Claws expire fast: their memory only exists to bridge one or two
    frames where the detector loses a real claw (border-contact zeroing
    while the partner walks nearby). Items remembered by the big-sprite
    path keep the long TTL they always had.
    """
    ttl_by_category = ttl_by_category or {"claw": 4}
    return {cell: value for cell, value in remembered.items()
            if done - value[1] <= ttl_by_category.get(value[0], 25)
            and cell != player}


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


def committed_wall_dash(committed_wall, player, done, ttl=3, last_dash=None):
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
    if committed_wall is None or committed_wall[0] != player:
        return False
    if last_dash is not None and last_dash >= committed_wall[1]:
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
        if category == "claw":
            # A claw is targeted via its own mask (claw > .10 with item
            # <= .06); patching "item" would disqualify it instead.
            if values.get("claw", 0.0) <= .10 and values["item"] <= .06:
                patched = dict(values)
                patched["claw"] = .12
                merged[cell] = patched
        elif values["item"] <= .06:
            patched = dict(values)
            patched[category] = max(patched[category], .07)
            patched["item"] = .07
            merged[cell] = patched
    return merged


def shift_items_left(remembered):
    """Scroll compensation: the world moved one column left."""
    return {(row, col - 1): value
            for (row, col), value in remembered.items() if col - 1 >= 0}


def should_reenable(disabled_at, done, span=REENABLE_ACTIONS):
    """True once enough actions have passed to justify retrying the consumable."""
    return disabled_at is not None and done - disabled_at >= span


def jittered_delay(base, jitter, rand=random.random):
    """Base delay plus a small random extra so taps do not tick uniformly."""
    return base + rand() * jitter


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


def resolve_player(info, expected):
    """Blend vision with dead reckoning: veto teleports, bridge weak frames.

    Vision wins while it is confident and physically plausible. A confident
    detection more than two cells from the expected position is treated as a
    misdetection when the expected cell still shows any player signal, and a
    weak frame falls back to the expected position instead of stalling.
    """
    best, score = player_cell(info)
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
            if distance > previous_distance:
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
    p.add_argument("--interval", type=float, default=.65)
    p.add_argument("--jitter", type=float, default=.35,
                   help="random extra seconds added to each action pause")
    p.add_argument("--batch-size", type=int, default=2, choices=(1, 2, 3))
    p.add_argument("--debug-screenshots", action="store_true")
    p.add_argument("--verbose", action="store_true", help="human-readable status for every scan")
    p.add_argument("--progress-percent", type=int, default=0, help="compact update interval in percent")
    p.add_argument("--min-confidence", type=float, default=.80)
    p.add_argument("--adb", default=bot.ADB_DEFAULT)
    p.add_argument("--serial", default=bot.SERIAL_DEFAULT)
    p.add_argument("--out", type=Path, default=Path("outputs"))
    args = p.parse_args()
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
    prev_fresh_suspects = set()
    committed_wall = None
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
    stable_board = None
    unreliable = 0
    player_unreliable = 0
    item_burst_waits = 0
    overlay_waits = 0
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
                event["milestone_claim"] = claim
                # 3 frames cover the badge's fade-out; 20 blocked the
                # NEXT chest when it lit up right after a claim (run
                # 20260820T192556: the 12,000m badge appeared 19 frames
                # after the 11,000m claim and was never claimed).
                chest_cooldown = 3
                bot.log_event(log, event)
                if args.verbose:
                    progress(done, args.steps,
                             "Cofre de milestone reclamado", "32")
                continue

        if bot.tutorial_overlay_center(image) is not None:
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
            time.sleep(args.interval); continue

        overlay_waits = 0
        if previous_action == "move" and expected_rollback is not None:
            # The last move was not followed by a rejection toast: it landed.
            rejected_streak = 0
        if det.state != "digiworld" or not det.board or det.confidence < args.min_confidence:
            unreliable += 1
            event["action"] = f"WAIT: unreliable board ({unreliable}/5)"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "Tablero inestable - nuevo escaneo", "33")
            if unreliable >= 5:
                show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
                return 2
            time.sleep(args.interval); continue
        unreliable = 0
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
        elif max(abs(a - b) for a, b in zip(det.board, stable_board)) > 18:
            event["board_correction"] = {
                "detected": list(det.board),
                "used": list(stable_board),
                "reason": "rejected sudden grid jump",
            }
            det = bot.Detection(det.state, det.confidence, stable_board,
                                det.reason + "; stable board retained")

        info = strategy.cells(image, det.board)
        player, player_score, player_source = resolve_player(info, expected_player)
        # The red sprite blob proved the most stable locator for oversized
        # partners; it also vetoes item-glow false positives that sneak just
        # over the vision threshold. The buggy highlight cross stays last.
        large = strategy.find_large_player(
            image, det.board,
            item_cells={cell for cell, values in info.items()
                        if values["item"] > .06})
        player, player_score, player_source = veto_with_blob(
            player, player_score, player_source, large)
        if player_source == "vision" and player_score < .08:
            cross = strategy.player_from_highlights(info, expected=expected_player)
            if cross is not None:
                player, player_score, player_source = cross, .30, "highlight-cross"
        memory_streak = memory_streak + 1 if player_source == "memory" else 0
        if player_source != "vision":
            event["player_resolution"] = {"cell": list(player), "source": player_source,
                                          "score": round(player_score, 3)}
        if (player_source == "vision" and player_score < .08) or memory_streak > 2:
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
            time.sleep(max(args.interval, 1.0)); continue
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
        # Claw sightings are remembered for every partner: the detector
        # drops a real claw for a frame when the sprite brushes its border
        # (user-confirmed at run 20260820T181916 event 83), and claws only
        # move with the scroll.
        for cell, values in info.items():
            if (values.get("claw", 0.0) > .10 and values["item"] <= .06
                    and cell != player):
                remembered_items[cell] = ("claw", done)
        remembered_items = prune_remembered_items(remembered_items, done, player)
        if remembered_items:
            info = merge_remembered_items(info, remembered_items, player)
        visible_items = [cell for cell, values in info.items() if values["item"] > .06]
        # A pickup animation flickers the item set between frames; a rich but
        # STABLE board is not an animation and deciding on it is safe. Waiting
        # two frames on every re-plan burned ~25s of wall clock in one run.
        current_item_cells = frozenset(visible_items)
        flickering = items_flickering(current_item_cells, prev_item_cells)
        # Mid-board arrivals that neither the scroll nor a broken pyramid
        # explains are confetti: ignored as targets for one frame instead
        # of waiting (the burst WAIT cost ~9s per run and still leaked).
        fresh_suspects = suspect_appearances(
            current_item_cells, prev_item_cells,
            shift=scrolls_since_frame,
            attack_cell=(previous_attack_target
                         if previous_action == "attack" else None))
        suspect_items = combined_suspects(fresh_suspects, prev_fresh_suspects,
                                          current_item_cells)
        prev_fresh_suspects = fresh_suspects
        prev_item_cells = current_item_cells
        scrolls_since_frame = 0
        if suspect_items:
            event["suspect_items"] = sorted(list(cell) for cell in suspect_items)
        if len(visible_items) >= 3 and item_burst_waits < 2 and flickering:
            item_burst_waits += 1
            event["action"] = (f"WAIT: possible pickup animation; {len(visible_items)} "
                               f"item cells ({item_burst_waits}/2)")
            if args.debug_screenshots:
                safe_stamp = stamp.replace(":", "").replace("+", "_")
                wait_path = run_dir / f"animation_wait_{done:04d}_{safe_stamp}.png"
                bot.diagnostic(image, det).save(wait_path)
                event["debug"] = str(wait_path)
            bot.log_event(log, event)
            # The sparkle animation clears in well under a second, and the
            # next loop pass re-verifies with a fresh frame anyway; the old
            # max(interval, 1.0) doubled every wait's real cost.
            time.sleep(.4); continue
        item_burst_waits = 0
        preview = strategy.sixth_column_preview(image, det.board)
        if preview is not None and any(preview):
            event["sixth_column"] = preview
        item_goals = pickup_goals(info, player)
        # Batch-2 is adaptive: on an item-free board it may safely advance up
        # to three cells. Any visible pickup immediately restores the more
        # careful two-click limit.
        effective_batch_size = adaptive_batch_limit(args.batch_size, item_goals)
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
            if not result["broken"]:
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
        wall_stable = (wall_now is not None and committed_wall is not None
                       and committed_wall[0] == wall_now
                       and done - committed_wall[1] <= 3)
        if wall_now is not None:
            committed_wall = (wall_now, done)
        action, reason = strategy.choose(info, previous_direction,
                                         attacks_enabled, dashes_enabled,
                                         ignored_targets=(set(banned_targets.keys())
                                                          | suspect_items),
                                         player=player, preview=preview,
                                         hunt_walls=wall_stable)
        if (action is not None and action[0] != "dash" and dashes_enabled and
                wall_now is None and committed_wall_dash(committed_wall, player,
                                                         done, last_dash=last_dash)):
            action, reason = ("dash", player, "right"), "committed wall dash"
            committed_wall = None
        if corridor_dash_due(action, last_attack, done, preview, dashes_enabled):
            action, reason = ("dash", player, "right"), "corridor dash"
        if action is None:
            event["action"] = "STOP: no safe action"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "STOP - sin acción segura", "31")
            show_run_summary(done, args.steps, started_at, collected, energy_start, read_energy_counter(image), "33")
            return 4
        kind, target, direction = action
        if args.verbose:
            color = "93" if item_goals else "36"
            progress(done, args.steps, plan_status(kind, direction, reason, len(item_goals)), color)
        event["reason"] = reason
        event["batch_limit"] = effective_batch_size
        if effective_batch_size == 3 and args.batch_size == 2:
            event["batch_mode"] = "adaptive-3: no visible items"
        sent = []

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
            # The dash consumes any wall commitment and advances the scroll
            # three columns, so remembered items shift with it.
            last_dash = done
            committed_wall = None
            for _ in range(3):
                remembered_items = shift_items_left(remembered_items)
            scrolls_since_frame += 3
        else:
            x, y = bot.cell_center(det.board, *target)
            if kind == "attack":
                pending_attack_inv = read_drop_counters(image)
                last_attack = (target[0], done)
            bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
            sent.append({"type": kind, "target_cell": list(target), "adb_xy": [x, y]})
            expected_rollback = player
            expected_player = (player if kind == "attack"
                               else expected_after_move(target, direction))
            if kind == "move" and direction == "right" and target[1] >= 2:
                remembered_items = shift_items_left(remembered_items)
                committed_wall = None
                scrolls_since_frame += 1
            pickup = item_category(info[target]) if kind == "move" else None
            if pickup:
                collected[pickup] += 1

            # Never batch through an attack or a pickup animation.
            first_has_item = is_pickup(info[target])
            if (kind == "move" and not approaching_wall and not first_has_item
                    and done + 1 < args.steps):
                remaining = min(effective_batch_size - 1, args.steps - done - 1)
                if loop_guard:
                    remaining = 0
                followups = safe_followup_moves(
                    info, player, target, direction, remaining, item_goals)
                for screen_target, checked in followups:
                    time.sleep(jittered_delay(args.interval, args.jitter))
                    x2, y2 = bot.cell_center(det.board, *screen_target)
                    bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x2), str(y2))
                    sent.append({"type": "move", "target_cell": list(screen_target),
                                 "validated_from_cell": list(checked), "adb_xy": [x2, y2]})
                    expected_player = expected_after_move(screen_target, direction)
                    if direction == "right" and screen_target[1] >= 2:
                        remembered_items = shift_items_left(remembered_items)
                        committed_wall = None
                        scrolls_since_frame += 1
                    pickup = item_category(info[checked])
                    if pickup:
                        collected[pickup] += 1

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
        previous_attack_target = target if kind == "attack" else None
        if kind == "dash":
            previous_dash_player = player
            previous_dash_obstacles = consecutive_right_obstacles(info, player)
        previous_direction = direction
        time.sleep(jittered_delay(
            max(args.interval, 2.0 if kind in ("dash", "attack") else args.interval),
            args.jitter))

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
