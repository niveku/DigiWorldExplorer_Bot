#!/usr/bin/env python3
"""Fast, bounded DigiWorld explorer using the conservative detector."""

from __future__ import annotations

import argparse
import heapq
import itertools
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
# Measured across every ground-truth frame: real pyramids score 0.88-0.99,
# while border decor, sprite parts, and apex remnants stay at or below 0.24.
# The old 0.18 threshold sat inside the noise band and flickered constantly.
PYRAMID_THRESHOLD = .45


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
            # Claw pickups (garra refund, 200 shards) are yellow slashes on a
            # dark disc: bright saturated yellow (live capture ~254,223,50).
            # Gatomon's own yellow paws bleed into neighbor cells, but that
            # bleed either touches the cell border (the paw reaches in from
            # outside) or stays under ~0.07 in the interior, while a real
            # claw's centered slashes score ~0.13 with a clean border.
            claw_mask = (r > 200) & (g > 170) & (b < 120)
            ch_, cw_ = claw_mask.shape
            bh, bw = max(2, int(ch_ * .12)), max(2, int(cw_ * .12))
            claw_border = np.zeros_like(claw_mask)
            claw_border[:bh, :] = claw_border[-bh:, :] = True
            claw_border[:, :bw] = claw_border[:, -bw:] = True
            claw_score = float(claw_mask[~claw_border].mean())
            if float(claw_mask[claw_border].mean()) > .01:
                claw_score = 0.0
            result[(row, col)] = {
                "player": float(max(red_player.mean(), bright_neutral_player.mean(),
                                    shadow_player_score)),
                "claw": claw_score,
                "orange": float(orange_mask.mean()),
                "pink": float(pink_mask.mean()),
                "green": float(green_mask.mean()),
                "item": float(max(orange_mask.mean(), pink_mask.mean(), green_mask.mean())),
                # Type discriminators (run 20260820T041234): the purple
                # ticket's white card body separates it from the steps paws
                # (white .096 vs .002), and the green ticket's saturated
                # card green separates it from the pale dash orb (.089 vs
                # .000). The HUD counters proved the values: paws +5 steps,
                # orb +1 dash, tickets +1 each.
                "white": float(((r > 215) & (g > 215) & (b > 215)).mean()),
                "card_green": float(((g > 140) & (g < 200) & (r < 110) &
                                     (g.astype(int) > b.astype(int) + 40)).mean()),
                "pyramid": float(((pb > 70) & (pr > 45) &
                                  (pb.astype(int) > pg.astype(int)+10)).mean()),
                "highlight": float(highlight_mask.mean()),
            }
    return result


def shortest_action(info, player, targets, allow_obstacles=True,
                    prefer_direction=None):
    """Weighted path: empty field costs 1, destructible pyramid costs 5.

    A garra costs 200 shards plus the 40-shard follow-up step, minus
    roughly one step of expected drop value (50.9% break-drop rate at
    ~+20 energy) - about five steps at 40 shards each. Pricing it at 2
    made a one-attack shortcut tie a free two-step detour and win by pop
    order (run 20260820T183527 attacks 25/85 spent garras beside free
    detours). Breaking through still wins where no free path exists.

    A rightward step taken from a row that holds no target costs slightly
    more: it scrolls the whole world (targets included) one column left
    without getting closer to picking anything, so aligning the row first
    - vertical steps do not scroll - must win ties. Run 20260820T181916
    events 188-192 rode row 0 past row-1 oranges until they turned
    perishable."""
    target_rows = {cell[0] for cell in targets}
    # A rightward step scrolls the world one column left, so a target
    # already in the perishable band (columns 0-1) is ERODED by every
    # right step of its own route. Run 20260821T215254 n=197 priced a
    # 5-step right-around of two walled-off perishables cheaper than
    # breaking through, and the first step scrolled both off the board.
    # No route to a column<=1 target may ever include a right step.
    fragile_target = any(cell[1] <= 1 for cell in targets)
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
            values = info[nxt]
            # A cell holding a pickup is slightly cheaper: between two
            # equal routes the bot must take the one that collects
            # something on the way (run 20260820T184744 events 194-196
            # rode an empty row past reachable paws).
            free_cost = (0.9 if (values["item"] > .06 or
                                 values.get("claw", 0.0) > .10) else 1)
            if name == "right" and fragile_target:
                continue
            step_cost = 5 if obstacle else free_cost
            if name == "right" and pos[0] not in target_rows:
                step_cost += 0.05
            # Hysteresis on ties: detection noise flips equal-cost routes
            # frame to frame (run 20260821T213642 n=32-34 alternated the
            # up-around and down-around of one pyramid). The FIRST step
            # that continues the previous direction gets an epsilon edge.
            if not path and name == prefer_direction:
                step_cost -= 0.001
            nc = cost + step_cost
            if nc < best.get(nxt, 999):
                best[nxt] = nc
                heapq.heappush(queue, (nc, nxt, path + [(nxt, obstacle, name)]))
    return None


def find_large_player(image, board, min_pixels=120, item_cells=()):
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
    # Orange pickup cards pass the red filter and stretch the bounding box
    # far enough to disqualify the whole blob; mask them out.
    orange = (r > 180) & (g > 55) & (g < 190) & (b < 100)
    mask = red & ~orange
    # A card's dark-red edge shading survives the orange filter (g ~ 50) and
    # once produced a 0.05-score ghost blob beside the item that dragged the
    # bot across the board. Cells already classified as items contribute no
    # sprite pixels.
    cell_w, cell_h = (x1 - x0) / 5, (y1 - y0) / 5
    # Mask item cells WITH a 30% margin: a card sliding across a cell
    # border leaves a red sliver in the neighbor cell that per-cell
    # masking misses (run 20260820T192556 event 191: two straddling
    # orange cards formed a 0.027 ghost blob, got the 3x3 around it
    # wiped, and cost a real orange to the scroll).
    height_px, width_px = mask.shape
    margin = 0.3
    for row, col in item_cells:
        ya = max(0, int((row - margin) * cell_h))
        yb = min(height_px, int((row + 1 + margin) * cell_h))
        xa = max(0, int((col - margin) * cell_w))
        xb = min(width_px, int((col + 1 + margin) * cell_w))
        mask[ya:yb, xa:xb] = False
    ys, xs = np.where(mask)
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
    # With the margin masking, residual card slivers score ~0.007 while
    # the weakest real FM frame (sprite overflowing the top row) scores
    # 0.031: the floor sits between them with 3x margin on both sides.
    if score < .02:
        return None
    return (row, col), score


def pickup_type(values):
    """Classify a pickup cell into its economic type, or None.

    Measured values (run 20260820T041234 HUD deltas): orange +20 energy,
    claw +1 garra (200 shards), dash orb +1 dash (400), paws +5 steps
    (200), tickets +1 ticket (negligible).
    """
    if values.get("claw", 0.0) > .10:
        return "claw"
    if values.get("orange", 0.0) > .06:
        return "orange"
    if values.get("green", 0.0) > .06:
        return ("green_ticket" if values.get("card_green", 0.0) > .03
                else "dash_orb")
    if values.get("pink", 0.0) > .06:
        return ("purple_ticket" if values.get("white", 0.0) > .05
                else "steps")
    return None


def suppress_sprite_leaks(info, player):
    """Wipe item scores in the 3x3 around an oversized partner's cell.

    A big sprite's colored parts (FM's orange wings, white chest) read as
    pickups in the cells its body covers, so the bot chases its own wings
    ('adjacent item' ping-pong, run 20260820T021629) and waits out phantom
    pickup animations. Pyramid, player, and highlight scores stay intact.
    """
    cleaned = {}
    for cell, values in info.items():
        if (max(abs(cell[0] - player[0]), abs(cell[1] - player[1])) <= 1):
            values = dict(values, orange=0.0, pink=0.0, green=0.0, item=0.0,
                          claw=0.0)
        cleaned[cell] = values
    return cleaned


def sixth_column_preview(image, board, min_strip=8):
    """Peek at the sliver of column 5 visible right of the board edge.

    Returns a list of five booleans (pyramid incoming per row), or None when
    the frame has no usable sliver. Only presence of a pyramid is readable
    in that ~15% of a cell; items and anything subtler are not.
    """
    a = np.asarray(image)
    x0, y0, x1, y1 = board
    strip_end = min(a.shape[1], x1 + int((x1 - x0) / 5 * .18))
    if strip_end - x1 < min_strip:
        return None
    cell_h = (y1 - y0) / 5
    result = []
    for row in range(5):
        ya = round(y0 + row * cell_h) + 8
        yb = round(y0 + (row + 1) * cell_h) - 12
        z = a[ya:max(ya + 1, yb), x1 + 2:strip_end]
        zp = z[:max(1, int(z.shape[0] * .55))]
        pr, pg, pb = zp[:, :, 0], zp[:, :, 1], zp[:, :, 2]
        pyramid = ((pb > 70) & (pr > 45) &
                   (pb.astype(int) > pg.astype(int) + 10)).mean()
        # The board's own frame decor keeps the strip at 0.12-0.24 on every
        # measured frame; a real incoming pyramid reads 0.93-1.0.
        result.append(bool(pyramid > .5))
    return result


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


def nearest_dash_wall(info, player, preview=None):
    """Launch cell left of the nearest run of >=3 pyramids, or None.

    A dash always travels three cells to the right and destroys everything in
    its path, so a wall of three is the cheapest possible pyramid breaker.
    Walls touching the left board edge have no launch cell and are skipped.
    A run that reaches the right edge counts one more when the sixth-column
    preview shows the next pyramid already scrolling in.
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
            length = col - start
            if col == 5 and preview is not None and preview[row]:
                length += 1
            if length >= 3 and start >= 1:
                launch = (row, start - 1)
                distance = abs(player[0] - row) + abs(player[1] - launch[1])
                if best is None or distance < best[0]:
                    best = (distance, launch)
    return best[1] if best else None


def plan_tour(player, items, max_items=6):
    """Order pickups by total steps, losing none, planned in advance.

    User directive 2026-08-22. The physics make this exact and cheap:
    the board only scrolls on OUR rightward steps, so collecting an item
    whose effective column is c costs a known scroll count and kills
    every remaining item left of it. All orders of up to six items are
    simulated; the winner keeps the most items, then costs the fewest
    steps, then leaves the bot furthest right (best final position).
    Urgency is emergent - a dying item forces itself to the front only
    when some other order would actually lose it - and the order is
    stable frame to frame because relative positions survive the scroll.
    """
    items = sorted(items, key=lambda cell: cell[1])[:max_items]
    if not items:
        return []
    best_key, best_order = None, []
    for order in itertools.permutations(items):
        row, col = player
        scrolls = 0
        cost = 0
        collected = []
        for r, c in order:
            c_eff = c - scrolls
            if c_eff < 0:
                break
            travel = c_eff - col
            cost += abs(r - row) + abs(travel)
            if travel > 0:
                scrolls += max(0, col + travel - 1)
                col = min(col + travel, 1)
            else:
                col = c_eff
            row = r
            collected.append((r, c))
        key = (-len(collected), cost, -scrolls)
        if best_key is None or key < best_key:
            best_key, best_order = key, collected
    return best_order


def choose(info, previous_direction=None, attacks_enabled=True, dashes_enabled=True,
           ignored_targets=(), player=None, preview=None, hunt_walls=True,
           suspect_cells=()):
    # A caller that already resolved the player (dead reckoning, large-sprite
    # locator) passes it in; per-cell scores stay authoritative otherwise.
    if player is None:
        player, pscore = max(((p, v["player"]) for p, v in info.items()),
                             key=lambda q: q[1])
        if pscore < .08:
            return None, f"player confidence too low ({pscore:.3f})"
    ignored = set(ignored_targets)

    # Cells a loop breaker has banned are invisible as goals: an unreachable
    # or misdetected pickup must not keep the pathfinder pacing forever.
    orange_items = {p for p, v in info.items()
                    if v["orange"] > .06 and p != player and p not in ignored}
    other_items = {p for p, v in info.items()
                   if v["item"] > .06 and p != player and p not in ignored}
    # Mid-tier pickups sit between energy and tickets: claw +1 garra (200
    # shards), dash orb +1 dash (400), paws +5 steps (200). Tickets (+1,
    # negligible per the user) stay in the lowest tier and never justify
    # passing up a mid-tier target.
    claw_items = {p for p, v in info.items()
                  if v.get("claw", 0.0) > .10 and v["item"] <= .06
                  and p != player and p not in ignored}
    # "claw" is listed here too: a claw whose item mask flickers past .06
    # leaves claw_items for that frame, and run 20260821T192126 n=122
    # dashed exactly such a claw off the board because the veto no longer
    # saw it as mid-tier.
    mid_items = claw_items | {p for p in other_items
                              if pickup_type(info[p]) in ("claw", "dash_orb",
                                                          "steps")}

    # A non-orange pickup that needs leftward travel is only worth a
    # detour its value pays for: a claw or paws (200 shards) covers two
    # 40-shard steps plus vanish risk (run 20260820T181916 event 83), but
    # a dash orb is a full 400-shard dash and pays for five (run
    # 20260821T220436 n=52-62 abandoned an orb at distance 5 and the
    # next explore step scrolled it off).
    def cheap_detour(cell):
        reach = 5 if pickup_type(info[cell]) == "dash_orb" else 2
        return (cell[1] >= player[1] or
                abs(cell[0] - player[0]) + abs(cell[1] - player[1]) <= reach)
    mid_items = {cell for cell in mid_items if cheap_detour(cell)}
    other_items = {cell for cell in other_items if cheap_detour(cell)}

    # One-frame suspects are excluded as goals, but a dash's forward scroll
    # would delete them from the left band before the next frame can
    # adjudicate them (run 20260821T154754 n=578 dashed three suspects to
    # their death; all three were real). They veto dashes for that single
    # frame: phantoms vanish and the dash fires on the very next pass.
    suspect_risk = {cell for cell in suspect_cells
                    if cell != player and cell[1] <= 2}

    # The world only scrolls forward, and it only scrolls on rightward
    # moves: an orange in the left two columns is about to leave the board
    # forever, while a wall of pyramids survives a leftward detour intact.
    # Rescue first, dash after (run 20260820T061407 events 126/247 dashed
    # through a wall and scrolled left oranges to their death).
    # An adjacent pickup reachable WITHOUT scrolling goes first, urgency
    # included: up/down/left never advance the scroll, so nothing
    # perishable ages during the one-step grab (run 20260821T234344 n=9
    # abandoned a paws card one step away for a perishable three cells
    # down - the free grab costs the rescue zero erosion).
    for dr, dc, direction in DIRS:
        if direction == "right":
            continue
        cell = (player[0] + dr, player[1] + dc)
        if (0 <= cell[0] < 5 and 0 <= cell[1] < 5
                and cell in (orange_items | mid_items | other_items)):
            return ("move", cell, direction), f"adjacent item={cell}"

    # A visible wall of three pyramids is irresistible while dashes remain:
    # align with its launch cell and dash through it. Two in a row stay an
    # opportunistic dash (handled below) and never justify a detour.
    # hunt_walls gates only the DETOUR to a wall: a flickering pyramid score
    # makes "the nearest wall" change launch cell with every step, and the
    # approach is exempt from the loop bans, so an unstable launch produced
    # an unbreakable left-right oscillation (run 20260820T024149). The
    # caller enables hunting only when the same launch was seen on
    # consecutive frames; opportunistic same-row dashes are unaffected.
    if dashes_enabled and hunt_walls:
        launch = nearest_dash_wall(info, player, preview=preview)
        if launch is not None:
            # The wall dash's 3-column scroll deletes every off-path
            # pickup in the left three columns, so it defers to them
            # exactly like the pair dash does (run 20260820T191232
            # events 47-53 dashed away an adjacent orange plus paws,
            # ~300 shards, for a path with zero items). The wall
            # survives the rescue; normal routing resumes after it.
            wall_path = {(launch[0], col)
                         for col in range(launch[1] + 1, min(5, launch[1] + 4))}
            wall_risk = {cell for cell in (orange_items | mid_items | suspect_risk)
                         if cell not in wall_path and cell[1] <= 2}
            # The dash is ROUTING, not abandonment (user directive
            # 2026-08-21b, run 220436 n=136: launch one step up, orange
            # at (3,4) - the skipped dash would have broken three
            # pyramids AND left the orange three columns closer). Only
            # pickups the scroll would erode (wall_risk: left band,
            # off-path) defer the wall; a column>=3 orange survives and
            # rides closer.
            if wall_risk:
                launch = None
        if launch == player:
            return ("dash", player, "right"), "3+ pyramid wall: dash"
        if launch is not None:
            step = shortest_action(info, player, {launch}, allow_obstacles=False)
            if step:
                target, _, direction = step
                return ("move", target, direction), f"approach dash wall via {launch}"

    # An adjacent pickup costs a single step; grab it before anything else
    # so the bot never has to walk back for it afterwards. The RIGHTWARD
    # grab yields when its scroll would kill a column-0 pickup - that is
    # the only real erosion a one-step grab can cause.
    edge_risk = any(cell[1] == 0 for cell in (orange_items | mid_items))
    for dr, dc, direction in DIRS:
        if direction == "right" and edge_risk:
            continue
        cell = (player[0] + dr, player[1] + dc)
        if not (0 <= cell[0] < 5 and 0 <= cell[1] < 5):
            continue
        if cell in other_items or cell in claw_items:
            return ("move", cell, direction), f"adjacent item={cell}"

    # Two pyramids inside the 3-cell dash path cost the same 400 shards as
    # the two garras that would clear them, but the dash also advances three
    # cells and collects every pickup it crosses (runs 20260820T030138/030401
    # spent 11 garras and none of 25 dashes on exactly these XX / X.X
    # shapes, one with an orange sitting in the gap). The forward scroll
    # deletes off-path pickups in the left three columns after the dash, so
    # any such pickup vetoes it and the normal routing takes over.
    if dashes_enabled:
        def dash_path_pyramids(row, col):
            count = sum(1 for c in range(col + 1, min(5, col + 4))
                        if is_obstacle(info[(row, c)]))
            if col + 3 >= 5 and preview is not None and preview[row]:
                count += 1
            return count

        path = [(player[0], col)
                for col in range(player[1] + 1, min(5, player[1] + 4))]
        path_pyramids = dash_path_pyramids(*player)
        # A visible wall of three outranks a pair even while its detection
        # is still stabilizing (hunt_walls False): the instant pair dash was
        # firing first and spent the dash on 2 pyramids while a 3-wall sat
        # one row away (long run 20260820T033221).
        full_wall = nearest_dash_wall(info, player, preview=preview)
        # Tickets are worth ~nothing: only energy and mid-tier pickups may
        # veto a dash over scroll loss.
        at_risk = {cell for cell in (orange_items | mid_items | suspect_risk)
                   if cell not in path and cell[1] <= 2}
        # A bare two-pyramid pair no longer justifies 400 shards: the true
        # alternative is the free two-step detour (80), not two garras
        # (run 20260821T225908 burned nine dashes with empty paths). The
        # pair pays only with an item in its path, a third pyramid, or a
        # right-side target the dash genuinely approaches.
        path_items = any(info[cell]["item"] > .06
                         or info[cell].get("claw", 0.0) > .10
                         for cell in path)
        right_targets = any(cell[1] >= 3
                            for cell in (orange_items | mid_items))
        pair_worth = path_items or right_targets or path_pyramids >= 3
        # Only an IMMINENT wall (launch one row above or below) may hold
        # the pair back - it stabilizes and fires within a frame or two
        # (run 20260820T033221). A far wall blocked the pair without
        # producing any action of its own and the explorer spent two
        # garras instead (run 20260821T213642 n=128-132). A wall in the
        # player's OWN row never defers the pair: it is made of the very
        # pyramids the pair dash breaks, so waiting for it produced a
        # five-move tour/hunt ping-pong (run 20260822T142042 n=452-458,
        # preview pyramid grading the pair into a "wall" one column
        # right).
        if (path_pyramids >= 2 and pair_worth and not at_risk
                and (full_wall is None
                     or full_wall[0] == player[0]
                     or abs(full_wall[0] - player[0]) > 1
                     or path_pyramids >= 3)):
            return ("dash", player, "right"), \
                f"dash pair: {path_pyramids} pyramids in path"
        # A single vertical step that lands on a pair launch is worth taking:
        # the pair rule fires from there on the next frame. Only when no
        # full wall is in sight and no left-band pickup would pay for it.
        # The risk is judged against the LAUNCH row's path, not the current
        # row's: run 20260821T192126 n=117-121 looped (0,0)<->(1,0) for five
        # moves because a claw sat in the current row's path (exempt here)
        # but off the launch row's path (vetoing the dash there).
        if path_pyramids < 2 and full_wall is None:
            for dr in (-1, 1):
                launch = (player[0] + dr, player[1])
                if not 0 <= launch[0] < 5:
                    continue
                if launch in ignored or is_obstacle(info[launch]):
                    continue
                if dash_path_pyramids(*launch) < 2:
                    continue
                launch_path = {(launch[0], col)
                               for col in range(launch[1] + 1,
                                                min(5, launch[1] + 4))}
                launch_items = any(info[cell]["item"] > .06
                                   or info[cell].get("claw", 0.0) > .10
                                   for cell in launch_path)
                if not (launch_items or right_targets
                        or dash_path_pyramids(*launch) >= 3):
                    continue
                launch_risk = {cell
                               for cell in (orange_items | mid_items
                                            | suspect_risk)
                               if cell not in launch_path and cell[1] <= 2}
                if launch_risk:
                    continue
                return ("move", launch, "up" if dr == -1 else "down"), \
                    f"pair launch at {launch}"

    # (The direct-horizontal rule retired 2026-08-22: the tour planner
    # below chooses the same ride when it is the shortest plan, and it
    # also knows when that ride would erode something real.)

    # The whole collection is planned IN ADVANCE (user directive
    # 2026-08-22): shortest route over all pickups losing none. Erosion
    # only enters where it is real - visiting a column-c item kills
    # everything left of c-1, that is the entire physics - so urgency
    # emerges from the plan instead of interrupting it, and the order is
    # stable frame to frame because relative positions survive the
    # scroll. The panic rescue that dived for anything at column<=1 (and
    # caused the up-down indecision the user kept seeing) is gone. Dash
    # rules above keep their own erosion vetoes and worth gates.
    tour_items = orange_items | mid_items
    if tour_items:
        order = plan_tour(player, tour_items)
        if order:
            first = order[0]
            step = shortest_action(info, player, {first},
                                   allow_obstacles=attacks_enabled,
                                   prefer_direction=previous_direction)
            if step:
                target, obstacle, direction = step
                # The label names the FIRST target's real category: every
                # mid-tier pickup used to print as "claw", and the user
                # read a steps-card chase as a garra spent on nothing
                # (run 20260822T142042 n=499).
                if first[1] <= 1:
                    label = ("orange perishable" if first in orange_items
                             else "urgent pickup")
                elif first in orange_items:
                    label = "orange"
                else:
                    label = pickup_type(info[first]) or "pickup"
                return ("attack" if obstacle else "move", target, direction), \
                    f"{label} targets={order}"

    # Tickets remain as a last-resort target.
    if other_items:
        step = shortest_action(info, player, other_items,
                               allow_obstacles=attacks_enabled,
                               prefer_direction=previous_direction)
        if step:
            target, obstacle, direction = step
            return ("attack" if obstacle else "move", target, direction), \
                f"item targets={sorted(other_items)}"

    # Per game behavior confirmed by the user, Dash always goes right. A dash
    # costs 400 shards and measured drops average +14 energy, so spend it
    # only on three consecutive pyramids (the sixth-column preview may
    # supply the third when the run reaches the right edge).
    right_obstacles = 0
    for col in range(player[1] + 1, 5):
        if is_obstacle(info[(player[0], col)]):
            right_obstacles += 1
        else:
            break
    if (right_obstacles and player[1] + 1 + right_obstacles == 5 and
            preview is not None and preview[player[0]]):
        right_obstacles += 1
    if dashes_enabled and right_obstacles >= 3:
        # Same scroll-loss veto as the other two dash rules: off-path
        # pickups and one-frame suspects in the left band die to the
        # 3-column scroll, so they defer this dash for a frame too.
        dash_row = {(player[0], col)
                    for col in range(player[1] + 1, min(5, player[1] + 4))}
        corridor_risk = {cell for cell in (orange_items | mid_items | suspect_risk)
                         if cell not in dash_row and cell[1] <= 2}
        if not corridor_risk:
            return ("dash", player, "right"), \
                f"{right_obstacles} consecutive right obstacles"

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
        # A garra costs 200 shards against 80 for the two-step vertical
        # detour: while exploring, ANY pyramid - the forward blocker
        # included - loses to a free orthogonal cell (user complaint
        # 2026-08-21, repeated 'garras para nada'). Only a boxed-in
        # explorer still attacks its way forward.
        if obstacle:
            score -= 95
        # Curiosity (user idea 2026-08-21): with nothing else to do, a
        # vertical step toward a row whose right side holds pyramids is
        # a step toward a potential pair dash; each one breaks the tie
        # between equally boring lanes (8 explore-pocket loop bans in
        # run 20260821T222310).
        if direction in ("up", "down"):
            score += 6 * sum(1 for c in range(2, 5)
                             if is_obstacle(info[(nxt[0], c)]))
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
