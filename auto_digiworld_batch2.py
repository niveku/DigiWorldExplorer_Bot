#!/usr/bin/env python3
"""DigiWorld explorer with adaptive two/three-action screenshot batches."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import ImageDraw

import auto_digiworld as strategy
import digiworld_bot as bot


DIR_DELTA = {"right": (0, 1), "left": (0, -1), "down": (1, 0), "up": (-1, 0)}


def player_cell(info):
    return max(((p, v["player"]) for p, v in info.items()), key=lambda q: q[1])


def adaptive_batch_limit(requested, item_goals):
    """Allow three clicks only for Batch-2 frames without visible pickups."""
    return 3 if requested == 2 and not item_goals else requested


def progress(current, total, message, color="36"):
    """Print one compact, colored status line for interactive debug runs."""
    print(f"\033[{color}m{current}/{total}: {message}\033[0m", flush=True)


def plan_status(kind, direction, reason, item_count):
    if item_count:
        return f"Energie gesichtet! {item_count} Item(s) - Route wird neu berechnet"
    if kind == "dash":
        return "Dash geplant - mehrere Hindernisse voraus"
    if kind == "attack":
        return "Pyramide gesichtet - sicherer Angriff wird ausgefuehrt"
    labels = {"right": "rechts", "left": "links", "up": "oben", "down": "unten"}
    return f"Erkunde nach {labels.get(direction, direction)} - {reason}"


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
        # Never plan beyond an item because its pickup animation changes the frame.
        if cell["item"] > .06:
            break
        if direction == "right" and screen_target[1] >= 2:
            offset += 1
            screen_player = (screen_target[0], screen_target[1] - 1)
        else:
            screen_player = screen_target
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--interval", type=float, default=.65)
    p.add_argument("--batch-size", type=int, default=2, choices=(1, 2, 3))
    p.add_argument("--debug-screenshots", action="store_true")
    p.add_argument("--verbose", action="store_true", help="human-readable status for every scan")
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
        progress(0, args.steps, "Debuglauf gestartet - erster Scan", "32")
    done = 0
    attacks_enabled = True
    dashes_enabled = True
    previous_action = None
    previous_attack_target = None
    previous_dash_player = None
    previous_dash_obstacles = 0
    previous_direction = None
    stable_board = None
    unreliable = 0
    player_unreliable = 0
    item_burst_waits = 0
    recent_states = []

    while done < args.steps:
        image = bot.screenshot(args.adb, args.serial)
        det = bot.classify(image)
        stamp = datetime.now(timezone.utc).isoformat()
        event = {"time_utc": stamp, "next_index": done, "detection": bot.asdict(det)}
        if args.verbose:
            progress(done, args.steps, "Scanne Spielfeld und berechne neu ...", "90")

        if bot.tutorial_overlay_center(image) is not None:
            if previous_action == "attack":
                attacks_enabled = False
                previous_action = None
                event["action"] = "WAIT: attacks disabled after rejection"
            elif previous_action == "dash":
                dashes_enabled = False
                previous_action = None
                event["action"] = "WAIT: dashes disabled after rejection"
            else:
                event["action"] = "WAIT: overlay visible"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, str(event["action"]), "33")
            time.sleep(args.interval); continue

        if det.state != "digiworld" or not det.board or det.confidence < args.min_confidence:
            unreliable += 1
            event["action"] = f"WAIT: unreliable board ({unreliable}/5)"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "Spielfeld unsicher - neuer Scan", "33")
            if unreliable >= 5:
                return 2
            time.sleep(args.interval); continue
        unreliable = 0

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
        visible_items = [cell for cell, values in info.items() if values["item"] > .06]
        if len(visible_items) >= 3 and item_burst_waits < 2:
            item_burst_waits += 1
            event["action"] = (f"WAIT: possible pickup animation; {len(visible_items)} "
                               f"item cells ({item_burst_waits}/2)")
            if args.debug_screenshots:
                safe_stamp = stamp.replace(":", "").replace("+", "_")
                wait_path = run_dir / f"animation_wait_{done:04d}_{safe_stamp}.png"
                bot.diagnostic(image, det).save(wait_path)
                event["debug"] = str(wait_path)
            bot.log_event(log, event)
            time.sleep(max(args.interval, 1.0)); continue
        item_burst_waits = 0
        player, player_score = player_cell(info)
        if player_score < .08:
            player_unreliable += 1
            event["action"] = f"WAIT: player score {player_score:.3f} ({player_unreliable}/5)"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "Spielerposition unsicher - neuer Scan", "33")
            if player_unreliable >= 5:
                event["action"] = "STOP: five consecutive unreliable player frames"
                bot.log_event(log, event); return 3
            time.sleep(max(args.interval, 1.0)); continue
        player_unreliable = 0
        item_goals = {cell for cell, values in info.items()
                      if values["item"] > .06 and cell != player}
        # Batch-2 is adaptive: on an item-free board it may safely advance up
        # to three cells. Any visible pickup immediately restores the more
        # careful two-click limit.
        effective_batch_size = adaptive_batch_limit(args.batch_size, item_goals)
        if (previous_action == "attack" and previous_attack_target is not None and
                strategy.is_obstacle(info.get(previous_attack_target, {
                    "pyramid": 0, "item": 0
                }))):
            attacks_enabled = False
            previous_action = None
            event["attack_state"] = {
                "status": "disabled: previous attack had no visual effect",
                "target_cell": list(previous_attack_target),
            }
            previous_attack_target = None
        if previous_action == "dash" and previous_dash_player is not None:
            current_right_obstacles = consecutive_right_obstacles(info, player)
            if (player == previous_dash_player and
                    previous_dash_obstacles >= 2 and current_right_obstacles >= 2):
                dashes_enabled = False
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
        recent_states = recent_states[-4:]
        loop_guard = (len(recent_states) == 4 and
                      recent_states[0] == recent_states[2] and
                      recent_states[1] == recent_states[3])
        action, reason = strategy.choose(info, previous_direction,
                                         attacks_enabled, dashes_enabled)
        if action is None:
            event["action"] = "STOP: no safe action"
            bot.log_event(log, event)
            if args.verbose: progress(done, args.steps, "STOPP - keine sichere Aktion", "31")
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

        # Precompute and visualize the batch before sending any input.
        planned = [target]
        if kind == "move" and info[target]["item"] <= .06:
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
                event["action"] = "WAIT: dash button missing"
                bot.log_event(log, event)
                if args.verbose: progress(done, args.steps, "Dash nicht verfuegbar - plane neu", "33")
                continue
            bot.adb(args.adb, args.serial, "shell", "input", "tap",
                    str(control[0]), str(control[1]))
            sent.append({"type": "dash", "adb_xy": list(control)})
        else:
            x, y = bot.cell_center(det.board, *target)
            bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
            sent.append({"type": kind, "target_cell": list(target), "adb_xy": [x, y]})

            # Never batch through an attack or an orange pickup animation.
            first_has_item = info[target]["item"] > .06
            if kind == "move" and not first_has_item and done + 1 < args.steps:
                remaining = min(effective_batch_size - 1, args.steps - done - 1)
                if loop_guard:
                    remaining = 0
                followups = safe_followup_moves(
                    info, player, target, direction, remaining, item_goals)
                for screen_target, checked in followups:
                    time.sleep(args.interval)
                    x2, y2 = bot.cell_center(det.board, *screen_target)
                    bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x2), str(y2))
                    sent.append({"type": "move", "target_cell": list(screen_target),
                                 "validated_from_cell": list(checked), "adb_xy": [x2, y2]})

        event["action"] = sent
        bot.log_event(log, event)
        done += len(sent)
        if args.verbose:
            progress(done, args.steps, f"{len(sent)} Aktion(en) ausgefuehrt - neuer Scan", "32")
        previous_action = kind
        previous_attack_target = target if kind == "attack" else None
        if kind == "dash":
            previous_dash_player = player
            previous_dash_obstacles = consecutive_right_obstacles(info, player)
        previous_direction = direction
        time.sleep(max(args.interval, 2.0 if kind in ("dash", "attack") else args.interval))

    final = bot.screenshot(args.adb, args.serial)
    final_det = bot.classify(final)
    final.save(run_dir / "final.png")
    bot.diagnostic(final, final_det).save(
        run_dir / "final_diagnostic.png")
    event = {"time_utc": datetime.now(timezone.utc).isoformat(), "status": "complete",
             "steps": done, "run_dir": str(run_dir),
             "detection": bot.asdict(final_det)}
    bot.log_event(log, event)
    if args.verbose: progress(done, args.steps, "Lauf erfolgreich abgeschlossen", "32")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
