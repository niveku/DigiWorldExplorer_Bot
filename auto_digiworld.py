#!/usr/bin/env python3
"""Fast, bounded DigiWorld explorer using the conservative detector."""

from __future__ import annotations

import argparse
import heapq
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import digiworld_bot as bot


# Right is preferred for exploration, but left remains available for real
# targets behind the Digimon and as a last safe route around blockers.
DIRS = ((0, 1, "right"), (1, 0, "down"), (-1, 0, "up"), (0, -1, "left"))
PYRAMID_THRESHOLD = .18


def is_obstacle(values):
    """Detect clipped pyramids without mistaking purple/blue pickup art for one."""
    return values["pyramid"] > PYRAMID_THRESHOLD and values["item"] <= .06


def cells(image, board):
    """Return per-cell visual scores for player, orange item and pyramid."""
    a = np.asarray(image)
    x0, y0, x1, y1 = board
    result = {}
    for row in range(5):
        for col in range(5):
            xa = round(x0 + col*(x1-x0)/5) + 8
            xb = round(x0 + (col+1)*(x1-x0)/5) - 8
            ya = round(y0 + row*(y1-y0)/5) + 8
            yb = round(y0 + (row+1)*(y1-y0)/5) - 12
            z = a[ya:yb, xa:xb]
            r, g, b = z[:,:,0], z[:,:,1], z[:,:,2]
            orange_mask = (r > 180) & (g > 55) & (g < 190) & (b < 100)
            pink_mask = ((r > 170) & (b > 140) & (g < 170) &
                         (r.astype(int) > g.astype(int)+40))
            green_mask = ((g > 130) & (r < 150) &
                          (g.astype(int) > r.astype(int)+35) &
                          (g.astype(int) > b.astype(int)+25))
            red_player = ((r > 110) & (r.astype(int) > g.astype(int)+45) &
                          (r.astype(int) > b.astype(int)+25) & ~orange_mask)
            # Some Digimon forms are predominantly silver/white instead of red.
            # A compact bright-neutral sprite score keeps those forms detectable;
            # static pyramid highlights stay well below the player threshold.
            rgb = z.astype(int)
            bright_neutral_player = ((rgb.min(axis=2) > 165) &
                                     ((rgb.max(axis=2) - rgb.min(axis=2)) < 65))
            yellow_accent = ((r > 190) & (g > 140) & (b < 80))
            dark_sprite = ((r < 65) & (g < 65) & (b < 75))
            highlight_mask = ((b > 120) & (g > 90) &
                              (b.astype(int) > r.astype(int)+25))
            shadow_player_score = 0.0
            if (dark_sprite.mean() > .20 and yellow_accent.mean() > .008 and
                    highlight_mask.mean() > .20 and orange_mask.mean() < .04):
                # The small dark Diri form is nearly black; its two bright
                # yellow eyes are the stable discriminator from dark tiles.
                # The bottom board frame can occlude roughly a quarter of this
                # tiny form, so keep enough margin for row 4 detections.
                shadow_player_score = float(yellow_accent.mean() * 8)
            # A pyramid's tall apex bleeds into the bottom of the cell above
            # it. Sampling only the upper part of each crop keeps that bleed
            # from reading as a phantom obstacle there, while a real pyramid
            # still fills its own cell's upper half completely.
            zp = z[:max(1, int(z.shape[0] * .55))]
            pr, pg, pb = zp[:, :, 0], zp[:, :, 1], zp[:, :, 2]
            result[(row, col)] = {
                "player": float(max(red_player.mean(), bright_neutral_player.mean(),
                                    shadow_player_score)),
                "orange": float(orange_mask.mean()),
                "pink": float(pink_mask.mean()),
                "green": float(green_mask.mean()),
                "item": float(max(orange_mask.mean(), pink_mask.mean(), green_mask.mean())),
                "pyramid": float(((pb > 70) & (pr > 45) &
                                  (pb.astype(int) > pg.astype(int)+10)).mean()),
                "highlight": float(highlight_mask.mean()),
            }
    return result


def shortest_action(info, player, targets, allow_obstacles=True):
    """Weighted path: empty field costs 1, destructible pyramid costs 2."""
    queue = [(0, player, [])]
    best = {player: 0}
    while queue:
        cost, pos, path = heapq.heappop(queue)
        if pos in targets and path:
            return path[0]
        if cost != best[pos]:
            continue
        for dr, dc, name in DIRS:
            nxt = (pos[0]+dr, pos[1]+dc)
            if not (0 <= nxt[0] < 5 and 0 <= nxt[1] < 5):
                continue
            obstacle = is_obstacle(info[nxt])
            if obstacle and not allow_obstacles:
                continue
            nc = cost + (2 if obstacle else 1)
            if nc < best.get(nxt, 999):
                best[nxt] = nc
                heapq.heappush(queue, (nc, nxt, path + [(nxt, obstacle, name)]))
    return None


def find_large_player(image, board, min_pixels=120):
    """Locate an oversized partner sprite spanning several cells.

    Big partners (e.g. Imperialdramon Fighter Mode) dilute every per-cell
    player score below the acting threshold. This fallback collects the red
    sprite pixels over the whole board, takes a percentile bounding box, and
    anchors the logical cell at the sprite's feet. Red only: a bright-white
    mask also matched the meter text and the lit movable tiles, dragging the
    centroid a full cell sideways (run 20260820T012543). White oversized
    partners must rely on the highlight-cross and memory paths instead.

    Returns ((row, col), score) or None when no plausible sprite is found.
    """
    a = np.asarray(image)
    x0, y0, x1, y1 = board
    z = a[y0:y1, x0:x1]
    r, g, b = z[:, :, 0], z[:, :, 1], z[:, :, 2]
    red = ((r > 110) & (r.astype(int) > g.astype(int) + 45) &
           (r.astype(int) > b.astype(int) + 25))
    ys, xs = np.where(red)
    if len(xs) < min_pixels:
        return None
    x_lo, x_hi = np.percentile(xs, [5, 95])
    y_lo, y_hi = np.percentile(ys, [5, 95])
    width, height = x1 - x0, y1 - y0
    if (x_hi - x_lo) > width * .75 or (y_hi - y_lo) > height * .75:
        return None
    cell_w, cell_h = width / 5, height / 5
    foot_y = min(y_hi - cell_h * .3, height - 1)
    center_x = (x_lo + x_hi) / 2
    row = min(max(int(foot_y // cell_h), 0), 4)
    col = min(max(int(center_x // cell_w), 0), 4)
    score = min(float(len(xs)) / (cell_w * cell_h), 1.0)
    return (row, col), score


def player_from_highlights(info, threshold=.30, min_lit=2, expected=None):
    """Infer the player's logical cell from the movable-cell highlight cross.

    The game renders the orthogonally adjacent, walkable cells in bright
    blue. The cell with the most lit orthogonal neighbors is the player's
    logical position - independent of sprite size, which makes this the
    reliable locator for oversized partners whose bodies span many cells.
    """
    best = None
    for row in range(5):
        for col in range(5):
            lit = []
            for dr, dc, _ in DIRS:
                neighbor = (row + dr, col + dc)
                if 0 <= neighbor[0] < 5 and 0 <= neighbor[1] < 5:
                    value = info[neighbor]["highlight"]
                    if value > threshold:
                        lit.append(value)
            if len(lit) < min_lit:
                continue
            score = len(lit) + sum(lit)
            # The lit region is buggy and includes the walked trail, so it
            # can manufacture rival centers anywhere. With a dead-reckoned
            # position available, a candidate beyond teleport distance is an
            # artifact and is discarded; near candidates win near-ties.
            if expected is not None:
                distance = abs(row - expected[0]) + abs(col - expected[1])
                if distance > 2:
                    continue
                if distance <= 1:
                    score += 1.0 - 0.5 * distance
            if best is None or score > best[0]:
                best = (score, (row, col))
    return best[1] if best else None


def nearest_dash_wall(info, player):
    """Launch cell left of the nearest run of >=3 pyramids, or None.

    A dash always travels three cells to the right and destroys everything in
    its path, so a wall of three is the cheapest possible pyramid breaker.
    Walls touching the left board edge have no launch cell and are skipped.
    """
    best = None
    for row in range(5):
        col = 0
        while col < 5:
            if not is_obstacle(info[(row, col)]):
                col += 1
                continue
            start = col
            while col < 5 and is_obstacle(info[(row, col)]):
                col += 1
            if col - start >= 3 and start >= 1:
                launch = (row, start - 1)
                distance = abs(player[0] - row) + abs(player[1] - launch[1])
                if best is None or distance < best[0]:
                    best = (distance, launch)
    return best[1] if best else None


def choose(info, previous_direction=None, attacks_enabled=True, dashes_enabled=True,
           ignored_targets=(), player=None):
    # A caller that already resolved the player (dead reckoning, large-sprite
    # locator) passes it in; per-cell scores stay authoritative otherwise.
    if player is None:
        player, pscore = max(((p, v["player"]) for p, v in info.items()),
                             key=lambda q: q[1])
        if pscore < .08:
            return None, f"player confidence too low ({pscore:.3f})"
    ignored = set(ignored_targets)

    # A visible wall of three pyramids is irresistible while dashes remain:
    # align with its launch cell and dash through it. Two in a row stay an
    # opportunistic dash (handled below) and never justify a detour.
    if dashes_enabled:
        launch = nearest_dash_wall(info, player)
        if launch == player:
            return ("dash", player, "right"), "3+ pyramid wall: dash"
        if launch is not None:
            step = shortest_action(info, player, {launch}, allow_obstacles=False)
            if step:
                target, _, direction = step
                return ("move", target, direction), f"approach dash wall via {launch}"

    # Cells a loop breaker has banned are invisible as goals: an unreachable
    # or misdetected pickup must not keep the pathfinder pacing forever.
    orange_items = {p for p, v in info.items()
                    if v["orange"] > .06 and p != player and p not in ignored}
    other_items = {p for p, v in info.items()
                   if v["item"] > .06 and p != player and p not in ignored}

    # An adjacent pickup costs a single step; grab it before anything else so
    # the bot never has to walk back for it afterwards.
    for dr, dc, direction in DIRS:
        cell = (player[0] + dr, player[1] + dc)
        if 0 <= cell[0] < 5 and 0 <= cell[1] < 5 and cell in other_items:
            return ("move", cell, direction), f"adjacent item={cell}"

    # Never walk around a green/purple pickup that already lies on the clear
    # horizontal route to the right. This costs no detour and still preserves
    # orange priority for targets elsewhere on the board.
    direct_item = None
    for col in range(player[1] + 1, 5):
        cell = (player[0], col)
        if cell in other_items:
            direct_item = cell
            break
        if is_obstacle(info[cell]):
            break
    if direct_item is not None:
        # Pickup graphics can themselves have a high pyramid color score. All
        # preceding cells were checked as clear, so advance one cell right.
        target = (player[0], player[1] + 1)
        return ("move", target, "right"), f"direct horizontal item={direct_item}"

    targets = orange_items or other_items
    if targets:
        step = shortest_action(info, player, targets, allow_obstacles=attacks_enabled)
        if step:
            target, obstacle, direction = step
            kind = "orange" if orange_items else "item"
            return ("attack" if obstacle else "move", target, direction), f"{kind} targets={sorted(targets)}"

    # Per game behavior confirmed by the user, Dash always goes right. Spend
    # it only when at least two consecutive pyramids block that row.
    right_obstacles = 0
    for col in range(player[1] + 1, 5):
        if is_obstacle(info[(player[0], col)]):
            right_obstacles += 1
        else:
            break
    if dashes_enabled and right_obstacles >= 2:
        return ("dash", player, "right"), f"{right_obstacles} consecutive right obstacles"

    # Fast exploration: keep moving right. If blocked, destroy the obstacle;
    # if at an edge, choose a highlighted orthogonal neighbor without reversing.
    candidates = []
    for dr, dc, direction in DIRS:
        nxt = (player[0]+dr, player[1]+dc)
        if not (0 <= nxt[0] < 5 and 0 <= nxt[1] < 5):
            continue
        v = info[nxt]
        obstacle = is_obstacle(v)
        if obstacle and not attacks_enabled:
            continue
        base = {"right": 100, "down": 12, "up": 10, "left": -40}[direction]
        score = base + 20*v["highlight"]
        if previous_direction and {previous_direction, direction} in ({"left","right"},{"up","down"}):
            score -= 30
        candidates.append((score, nxt, obstacle, direction))
    if not candidates:
        return None, "no orthogonal candidate"
    # Cells banned by the loop breaker are avoided while any alternative
    # exists; falling back to them beats stalling in a fully banned pocket.
    preferred = [entry for entry in candidates if entry[1] not in ignored]
    _, target, obstacle, direction = max(preferred or candidates)
    return ("attack" if obstacle else "move", target, direction), "explore right"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--min-confidence", type=float, default=.82)
    p.add_argument("--adb", default=bot.ADB_DEFAULT)
    p.add_argument("--serial", default=bot.SERIAL_DEFAULT)
    p.add_argument("--out", type=Path, default=Path("outputs"))
    args = p.parse_args()
    try:
        args.adb = bot.resolve_adb(args.adb)
        args.serial = bot.resolve_serial(args.adb, args.serial)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 10
    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.out / "digiworld_auto_steps.jsonl"
    previous_direction = None
    previous_action = None
    attacks_enabled = True
    dashes_enabled = True
    actions_done = 0
    uncertain_frames = 0

    while actions_done < args.steps:
        started = time.monotonic()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        image = bot.screenshot(args.adb, args.serial)
        det = bot.classify(image)
        event = {"time_utc": stamp, "index": actions_done, "detection": bot.asdict(det)}
        if bot.tutorial_overlay_center(image) is not None:
            if previous_action == "attack":
                attacks_enabled = False
                previous_action = None
                event["action"] = "WAIT: attack rejected; attacks disabled, rerouting"
                bot.log_event(log_path, event); print(json.dumps(event))
                time.sleep(max(.5, args.interval)); continue
            if previous_action == "dash":
                dashes_enabled = False
                previous_action = None
                event["action"] = "WAIT: dash rejected; dashes disabled, rerouting"
                bot.log_event(log_path, event); print(json.dumps(event))
                time.sleep(max(.5, args.interval)); continue
            event["action"] = "WAIT: centered overlay/message visible"
            bot.log_event(log_path, event); print(json.dumps(event))
            time.sleep(max(.5, args.interval)); continue
        if det.state != "digiworld" or not det.board or det.confidence < args.min_confidence:
            uncertain_frames += 1
            event["action"] = f"WAIT: unreliable board ({uncertain_frames}/5)"
            bot.log_event(log_path, event); print(json.dumps(event))
            if uncertain_frames >= 5:
                event["action"] = "STOP: five consecutive unreliable frames"
                image.save(args.out / f"auto_stop_{stamp.replace(':','')}.png")
                bot.log_event(log_path, event); return 2
            time.sleep(max(.5, args.interval)); continue
        uncertain_frames = 0

        info = cells(image, det.board)
        action, reason = choose(info, previous_direction, attacks_enabled, dashes_enabled)
        event["reason"] = reason
        if action is None:
            event["action"] = "STOP: no safe action"
            bot.log_event(log_path, event); print(json.dumps(event)); return 3
        kind, target, direction = action
        if kind == "dash":
            control = bot.dash_button(image)
            if control is None:
                dashes_enabled = False
                event["action"] = "WAIT: dash button not detected; dashes disabled"
                bot.log_event(log_path, event); print(json.dumps(event)); continue
            x, y = control
        else:
            x, y = bot.cell_center(det.board, *target)
        bot.adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
        event["action"] = {"type": kind, "target_cell": list(target),
                           "direction": direction, "adb_xy": [x, y]}
        event["scores"] = info[target]
        bot.log_event(log_path, event)
        print(json.dumps(event, ensure_ascii=False))
        previous_direction = direction
        previous_action = kind
        actions_done += 1
        time.sleep(max(0, args.interval - (time.monotonic() - started)))

    # Always leave a final verified screenshot after the bounded run.
    time.sleep(max(.5, args.interval))
    final = bot.screenshot(args.adb, args.serial)
    final_det = bot.classify(final)
    final_path = args.out / "digiworld_auto_final.png"
    final.save(final_path)
    bot.diagnostic(final, final_det).save(args.out / "digiworld_auto_final_diagnostic.png")
    event = {"time_utc": datetime.now(timezone.utc).isoformat(), "status": "complete",
             "steps": args.steps, "detection": bot.asdict(final_det), "final": str(final_path)}
    bot.log_event(log_path, event); print(json.dumps(event, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
