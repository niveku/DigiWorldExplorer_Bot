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
            elif claw_score <= .10:
                # A claw standing in the row of the foreground ice loses
                # its bottom to it, and with it the area this threshold
                # reads. Run 20260828T215949 n=78 scored .091 and the bot
                # walked past a garra in plain sight (user: "por que no
                # bajo y tomo la garra"). Area cannot be stretched to
                # cover the gap - .091 sits inside the pyramid-glint
                # band, whose 99th percentile is .094 - so recognise the
                # sprite instead of measuring it: a claw is ~500 slash
                # pixels at about a third fill of their own bounding
                # box, and a bite from below removes pixels without
                # changing the fill. Both bands are needed; glints are
                # either too few pixels or far denser (95th pct fill
                # .64). Measured over the 12,250 recorded digiworld
                # frames: 528 cells fall inside both bands, 310 of them
                # already clearing the threshold on area alone and 125
                # below it. The item guard is what makes the rest safe -
                # the orange energy's yellow cap clears both bands on
                # its own, and pickup_type asks about the claw BEFORE
                # the orange, so without it energy would be renamed
                # garras. It drops 104, and the 21 that remain are
                # claws bitten by the ice, every one of them in row 4.
                claw_pixels = claw_mask & ~claw_border
                count = int(claw_pixels.sum())
                ys, xs = np.nonzero(claw_pixels)
                item_here = max(orange_mask.mean(), pink_mask.mean(),
                                green_mask.mean())
                if count >= 300 and item_here <= .06:
                    box = ((ys.max() - ys.min() + 1) *
                           (xs.max() - xs.min() + 1))
                    if .24 <= count / box <= .45:
                        # As much claw as the ice leaves visible: every
                        # reader of this score asks the same yes/no
                        # question of it, so report the unoccluded
                        # sprite's own median rather than invent a scale.
                        claw_score = .13
            # The same bite, the same answer, a different channel. A
            # dash orb read .0575 against .06 in run 20260828T230319
            # n=42, one step below the bot, and the board came back
            # empty (user: "no bajo un paso a recoger un Dash"). The
            # green family - orbs and tickets - is a compact sprite
            # like the claw: ~530 pixels at about 45% fill of its own
            # bounding box, and whatever eats part of it (the
            # foreground ice, or the neighbouring cell when the sprite
            # straddles the line) removes pixels without changing the
            # fill. Noise is either smaller (95th pct 280 pixels) or
            # solid (95th pct fill 1.0).
            #
            # 21 cells in the 12,250 recorded frames fall below the
            # threshold inside both bands, and all 21 are real - six of
            # them this very orb, tracked across n=37..42 as the belt
            # carried it from (4,4) to (4,1) with the bot never seeing
            # it. Checked by eye, all 21.
            #
            # Measuring the cell over its top 80% instead was tried and
            # REFUTED on the same corpus: it gains 101 detections and
            # loses 77 real ones, because a row-4 sprite is often drawn
            # low in its cell and the crop cuts it off. The occlusion is
            # real, but its share of the cell is not fixed enough to
            # divide by.
            green_score = float(green_mask.mean())
            if (green_score <= .06 and orange_mask.mean() <= .06
                    and pink_mask.mean() <= .06):
                count = int(green_mask.sum())
                if count >= 280:
                    ys, xs = np.nonzero(green_mask)
                    box = ((ys.max() - ys.min() + 1) *
                           (xs.max() - xs.min() + 1))
                    if .25 <= count / box <= .60:
                        # As much sprite as is visible; every reader
                        # asks the same yes/no question of this score,
                        # so report the unoccluded median.
                        green_score = .08
            result[(row, col)] = {
                "player": float(max(red_player.mean(), bright_neutral_player.mean(),
                                    shadow_player_score)),
                "claw": claw_score,
                "orange": float(orange_mask.mean()),
                "pink": float(pink_mask.mean()),
                "green": green_score,
                "item": float(max(orange_mask.mean(), pink_mask.mean(), green_score)),
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
                    prefer_direction=None, protect=(), avoid=(),
                    with_cost=False):
    """Weighted path: empty field costs 1, destructible pyramid costs 5.

    A garra costs 200 shards plus the 40-shard follow-up step, minus
    roughly one step of expected drop value (50.9% break-drop rate at
    ~+20 energy) - about five steps at 40 shards each. The +20 there is
    the passive regeneration tick, not the drop (see pickup_type): the
    instant yield of an attack is 0.3 energy over 357 recorded attacks,
    and a drop that lands as an ORANGE on the board is worth 125 when it
    is later walked onto. Which of the two the 50.9% refers to was never
    isolated, so the price of 5 stands unchanged until an experiment
    settles it - breaking one pyramid beside a clear board and reading
    the HUD before and after. Pricing it at 2
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
    # A scrolling right erodes left-band targets, so every route gets a
    # SCROLL BUDGET from its most fragile target: a column-0 target
    # tolerates none (run 20260821T215254 n=197: a right-around
    # scrolled two perishables off the board), a column-1 target
    # survives exactly one (user doctrine 2026-08-22, PNG debug_0148:
    # 'solo debería hacer cosas raras si el drop está en la columna 0'
    # - the blanket col<=1 ban outlawed natural routes and made garras
    # win by default), and anything further right does not care. Only
    # rights INTO column 2+ scroll; col0->col1 is free (run
    # 20260822T142042 n=194).
    # protect: later stops of the same plan - the leg to the FIRST
    # target must not scroll a later perishable off the board (boxed
    # pair (4,0)+(4,1): the lone-target budget allowed a right-around
    # whose single scroll killed the col-0 twin).
    scroll_budget = min((cell[1] if cell[1] <= 1 else 99)
                        for cell in set(targets) | set(protect))
    queue = [(0, player, [], 0)]
    best = {(player, 0): 0}
    while queue:
        cost, pos, path, scrolls = heapq.heappop(queue)
        if pos in targets and path:
            return (path[0], cost) if with_cost else path[0]
        if cost != best.get((pos, scrolls)):
            continue
        for dr, dc, name in DIRS:
            nxt = (pos[0]+dr, pos[1]+dc)
            if not (0 <= nxt[0] < 5 and 0 <= nxt[1] < 5):
                continue
            obstacle = is_obstacle(info[nxt])
            if obstacle and not allow_obstacles:
                continue
            # avoid: unadjudicated suspect cells are impassable ground
            # (replay harness 2026-08-22: choose() kept routing THROUGH
            # suspects the tap gate then refused - a decision/guard
            # contradiction that starved the tour in skip loops).
            # Targets themselves stay reachable.
            if nxt in avoid and nxt not in targets:
                continue
            values = info[nxt]
            # A cell holding a pickup is slightly cheaper: between two
            # equal routes the bot must take the one that collects
            # something on the way (run 20260820T184744 events 194-196
            # rode an empty row past reachable paws).
            free_cost = (0.9 if (values["item"] > .06 or
                                 values.get("claw", 0.0) > .10) else 1)
            # Screen column, not frame column: after k scrolls already
            # taken on this route the cell at frame col c sits at
            # screen col c-k, and only a tap into SCREEN column >=2
            # scrolls (review 2026-08-22, 'physics' lens). Charging by
            # frame column billed a phantom second scroll to any route
            # that scrolled once, detoured left around a pyramid and
            # stepped right again - the budget then pruned legal
            # one-scroll rescues and the epsilons fired on steps that
            # move nothing.
            scrolling_right = name == "right" and nxt[1] - scrolls >= 2
            nscrolls = scrolls + (1 if scrolling_right else 0)
            if nscrolls > scroll_budget:
                continue
            step_cost = 5 if obstacle else free_cost
            if scrolling_right and pos[0] not in target_rows:
                step_cost += 0.05
            # Tie-break: advance EARLY. User doctrine 2026-08-22
            # (overruling the one-run scroll-late rule): between routes
            # of equal taps and resources, the one that advances the
            # world rightward sooner is progress. Epsilons (<=0.006)
            # never outweigh a real cost gap.
            if scrolling_right:
                step_cost -= 0.002 * max(0, 3 - len(path))
            # Hysteresis on ties: detection noise flips equal-cost routes
            # frame to frame (run 20260821T213642 n=32-34 alternated the
            # up-around and down-around of one pyramid). The FIRST step
            # that continues the previous direction gets an epsilon edge.
            if not path and name == prefer_direction:
                step_cost -= 0.001
            nc = cost + step_cost
            key = (nxt, nscrolls)
            if nc < best.get(key, 999):
                best[key] = nc
                heapq.heappush(queue, (nc, nxt,
                                       path + [(nxt, obstacle, name)],
                                       nscrolls))
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


def pair_dash_pays(info, cell, wanted, extra_pyramids=0):
    """Is a dash launched from `cell` worth its 400 shards?

    ONE predicate, because the rule that walks toward a launch has to be
    the same rule that fires on arrival. When they drifted apart the bot
    walked to a launch the dash then refused, the explorer took over and
    walked it away, and the rule sent it back: run 20260828T211315
    n=32-38 spent seven paws circling a board that never changed - and
    it was standing ON the launch cell when it started.

    `wanted` is the set of pickups worth routing to; `extra_pyramids`
    lets the caller count a wall the preview promises but that has not
    landed yet.
    """
    path = [(cell[0], col) for col in range(cell[1] + 1, min(5, cell[1] + 4))]
    if not path:
        return False
    pyramids = sum(1 for c in path if is_obstacle(info[c])) + extra_pyramids
    if pyramids < 2:
        return False
    if pyramids >= 3:
        return True
    if any(info[c]["item"] > .06 or info[c].get("claw", 0.0) > .10
           for c in path):
        return True
    if any(other[0] == cell[0] and other[1] >= 3 for other in wanted):
        return True
    # No way around means the two-paw detour the veto quotes is not on
    # the board, and then the dash is the cheap answer after all.
    return not any(
        not is_obstacle(info[(row, cell[1])])
        and cell[1] + 1 < 5
        and not is_obstacle(info[(row, cell[1] + 1)])
        for row in (cell[0] - 1, cell[0] + 1) if 0 <= row < 5)


def pickup_type(values):
    """Classify a pickup cell into its economic type, or None.

    Measured values: orange +125 energy, claw +1 garra (200 shards),
    dash orb +1 dash (400), paws +5 steps (200), tickets +1 ticket
    (negligible).

    The orange was priced at +20 from 2026-08-20 to 2026-08-28 and that
    was the passive regeneration tick, not the pickup. Re-measured over
    every recorded run (n=623 frames whose plan stepped onto a KNOWN
    orange): the energy delta is +125 in 623 of them and never +20 more
    often than on a frame that picked nothing up (2.9% against 3.6%,
    which is the +20 tick arriving on its own ~28s cadence). One step
    costs 18.2 energy of run average (3014 charged steps), so an orange
    is worth about seven paws - the arithmetic that called a two-paw
    round trip for one "the losing side" was inverted by a factor of six.
    """
    # The item guard is part of what a claw IS, not an extra filter the
    # callers bolt on: claw_items has asked for both since 2026-08-22
    # (a pyramid's glints trip the slash detector) and this did not, so
    # the two disagreed about the same cell. The orange energy's yellow
    # cap is the case that made the gap bite - it can clear the claw
    # threshold on its own, and this function asks about the claw first,
    # so an orange came back a garra. A real claw's item score is ~.02.
    if values.get("claw", 0.0) > .10 and values.get("item", 0.0) <= .06:
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
        collected, cost, scrolls = simulate_tour(player, order)
        key = (-len(collected), cost, -scrolls)
        if best_key is None or key < best_key:
            best_key, best_order = key, collected
    return best_order


MID_DETOUR_ALLOWANCE = {"steps": 3, "claw": 5, "dash_orb": 10}


def walk_distance(info, start, goal):
    """Real steps from start to goal walking around pyramids (BFS)."""
    if start == goal:
        return 0
    frontier = [start]
    seen = {start}
    dist = 0
    while frontier:
        dist += 1
        nxt = []
        for pos in frontier:
            for dr, dc, _ in DIRS:
                cell = (pos[0] + dr, pos[1] + dc)
                if not (0 <= cell[0] < 5 and 0 <= cell[1] < 5):
                    continue
                if cell == goal:
                    return dist
                if cell in seen or is_obstacle(info[cell]):
                    continue
                seen.add(cell)
                nxt.append(cell)
        frontier = nxt
    return 99


def prune_low_value_mids(player, oranges, mids, types, info=None):
    """Drop mid-tier cards whose detour costs more than they refund.

    Paticas ROI: one move consumes 1 patica and a steps card returns
    EXACTLY +4 (user-verified on the HUD 2026-08-22; the 275-interval
    least-squares estimate of ~3.3 carried detection noise). A detour
    of 4+ steps is therefore never worth a bare card - allowance 3
    keeps it strictly profitable. A claw
    refunds a 200-shard garra (~5 steps), a dash orb a 400-shard dash
    (~10). Oranges are never pruned - one orange is worth a dash's
    whole yield. A mid stays when the best tour with it costs at most
    its allowance more than the best tour without it, and pruning
    never trades away another item.

    Rightward travel that scrolls the world is progress the explorer
    would make anyway, so the detour price is steps minus scrolls:
    only vertical and leftward walking counts against the card."""
    keep = set(mids)
    for mid in sorted(mids):
        pool = set(oranges) | keep
        with_mid = plan_tour(player, pool)
        if mid not in with_mid:
            continue
        without = plan_tour(player, pool - {mid})
        if len(without) < len(with_mid) - 1:
            continue
        _, cost_with, scrolls_with = simulate_tour(player, with_mid)
        _, cost_without, scrolls_without = simulate_tour(player, without)
        detour = (cost_with - scrolls_with) - (cost_without - scrolls_without)
        if info is not None:
            # The tour costs Manhattan steps, but pyramids force real
            # walking: the card at (0,1) priced at 3 steps cost 5 around
            # the pyramid at (2,1) - 5 paticas for a +4 card (run
            # 20260822T153206 n=52-56). Charge the mid the surcharge of
            # actually reaching it.
            detour += max(0, walk_distance(info, player, mid)
                          - abs(mid[0] - player[0]) - abs(mid[1] - player[1]))
        if detour > MID_DETOUR_ALLOWANCE.get(types.get(mid), 3):
            keep.discard(mid)
    return keep


def simulate_tour(player, order):
    """Walk one visiting order; return (collected, steps, scrolls)."""
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
    return collected, cost, scrolls


def dash_path_pyramids(info, row, col):
    """Obstacles a dash launched from (row, col) would break.

    The dash covers the three cells to the right of the launch. No
    preview extension: the player is pinned to columns 0-1 and a launch
    cell shares the player's column, so col + 3 never passes the edge.
    """
    return sum(1 for c in range(col + 1, min(5, col + 4))
               if is_obstacle(info[(row, c)]))


def choose(info, previous_direction=None, attacks_enabled=True, dashes_enabled=True,
           ignored_targets=(), player=None, preview=None, hunt_walls=True,
           suspect_cells=(), dash_stock=None, blocked_direction=None,
           allow_paid_detour=False, barren_cells=()):
    """Pick the next action, refusing to undo the step just taken.

    blocked_direction is the runner's receipt-backed report that the last
    charged step collected nothing and did not scroll: the board is
    byte-identical, so walking back re-enters a state already judged and
    the two goals that disagree about it will keep trading the player
    between two cells (run 20260823T143257 n=45-52: orange at (0,3) wins
    from row 1, dash-pair launch at (1,1) wins from row 0, six paws for
    zero progress; the explorer's own -30 reversal penalty never saw it
    because the two goals live in different branches).

    allow_paid_detour lifts the cost guard below: see the comment there.

    The veto is applied to the outcome rather than inside every branch:
    close the cell we came from and ask again. It never strands the
    player - if the closed board has no answer, the original stands.
    """
    action, reason = _choose(info, previous_direction, attacks_enabled,
                             dashes_enabled, ignored_targets, player, preview,
                             hunt_walls, suspect_cells, dash_stock,
                             barren_cells)
    if (blocked_direction is None or action is None
            or action[0] != "move" or action[2] != blocked_direction):
        return action, reason
    closed = {cell: (dict(values, pyramid=0.9) if cell == action[1] else values)
              for cell, values in info.items()}
    detour, detour_reason = _choose(closed, previous_direction, attacks_enabled,
                                    dashes_enabled, ignored_targets, player,
                                    preview, hunt_walls, suspect_cells,
                                    dash_stock, barren_cells)
    if detour is None or detour[1] == action[1]:
        return action, reason
    if detour[0] != "move" and not allow_paid_detour:
        # A wasted paw is 40 shards; a garra is 200 and a dash 400. The
        # veto exists to stop cheap waste, so it must never buy an
        # expensive action to avoid it - on (4,1) walled by (3,2) and
        # (4,2) the closed board's best answer is a garra at the wall
        # (run 20260823T151420 n=30).
        #
        # Unless the cheap answer is not cheap any more: the caller sets
        # allow_paid_detour once the same veto has already been overruled,
        # because a reversal the planner keeps repeating is not one wasted
        # paw but an unbounded run of them (run 20260824T051703 n=38-40,
        # a pocket walled by (0,2), (1,2) and (2,1): three paws of
        # up-down-up and five harness flags, ended only by the board
        # moving on its own).
        return action, reason
    return detour, f"{detour_reason} (no back-step)"


def _choose(info, previous_direction=None, attacks_enabled=True, dashes_enabled=True,
            ignored_targets=(), player=None, preview=None, hunt_walls=True,
            suspect_cells=(), dash_stock=None, barren_cells=()):
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
    # A pyramid's glints trip the claw slash detector, and a cell
    # cannot be both: the pyramid score (.88-.99, the strongest signal)
    # wins (replay harness 2026-08-22 n=107: claw .15 + pyramid .9 on
    # one cell, four identical refused decisions).
    claw_items = {p for p, v in info.items()
                  if v.get("claw", 0.0) > .10 and v["item"] <= .06
                  and not is_obstacle(v)
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

    # A steps card refunds ~3-5 paticas (130-200 shards, measured over
    # 275 counter intervals): losing one to a 400-shard dash whose
    # measured yield is ~+20E costs less than the veto it used to
    # trigger. Claws and dash orbs are real charge refunds and still
    # veto; oranges always do.
    # (That ~+20E is the regeneration tick again: over 352 recorded
    # dashes the very next frame reads +20 157 times, 0 141 times and
    # +125 never. A three-frame window does show oranges, but it also
    # contains ordinary steps, so what the dash itself collects is not
    # measured yet. The comparison is left standing rather than guessed:
    # a steps card is still the cheapest thing on the board either way.)
    steps_cards = {cell for cell in mid_items
                   if pickup_type(info[cell]) == "steps"}

    # (The left-band SUSPECT veto on dashes retired 2026-08-23. It was
    # written on 2026-08-21 - run 20260821T154754 n=578 dashed three
    # suspects to their death, all three real - under the old suspicion
    # stack, where anything freshly seen was suspect for two frames. The
    # world model classifies by ORIGIN: an item entering at the right
    # edge is explained and believed on sight, so what stays suspect is
    # an unexplained birth, which is what confetti is. Vetoing a
    # 400-shard wall-clearing dash on a probable phantom left the bot
    # dithering on the launch cell - run 20260823T074036 n=154-157 spent
    # three paws walking off it and back before dashing, and n=80-83 the
    # same. Real left-band pickups are still protected: they are BELIEVED
    # items, so they sit in orange_items/mid_items and in the runner's
    # left_band_risk, which every dash rule already honours.)

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
    #
    # Suspects excluded. Everywhere else in this file a left-band
    # suspect is confetti that can never be believed or targeted, and
    # this was the one rule that still walked to one: run
    # 20260828T223602 n=65 ate the orange at (3,3), the pickup burst
    # painted a card on (3,0) behind the bot, and the free-grab rule
    # spent a paw walking backwards onto it (user: "dio un paso para
    # atras sin razon... si ya habia pasado por esa celda y no habia
    # nada, por que ahora si habria de haber algo?"). A step onto a
    # maybe-item is free only when it was going that way anyway; this
    # loop skips 'right' by construction, so every step it takes is a
    # detour. Being wrong the other way costs nothing but three frames
    # of confirmation, and the item is adjacent the whole time.
    for dr, dc, direction in DIRS:
        if direction == "right":
            continue
        cell = (player[0] + dr, player[1] + dc)
        if (0 <= cell[0] < 5 and 0 <= cell[1] < 5
                and cell not in suspect_cells
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
        # If the standing start already reaches three REAL pyramids,
        # dash NOW - never walk to a "better" launch. Run
        # 20260822T175424 n=11-13: the sprite misread as a pyramid made
        # the wall run start one column early, the computed launch sat
        # one step BACK, and the dash from there broke 2 instead of the
        # 3 available in place (user: 'estaba totalmente de frente').
        standing_path = {(player[0], col)
                         for col in range(player[1] + 1, min(5, player[1] + 4))}
        standing_reach = sum(1 for cell in standing_path
                             if is_obstacle(info[cell]))
        standing_risk = {cell
                         for cell in (orange_items | mid_items)
                         if cell not in standing_path and cell[1] <= 2
                         and cell not in steps_cards}
        if standing_reach >= 3 and not standing_risk:
            return ("dash", player, "right"), "3+ pyramid wall: dash"
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
            wall_risk = {cell for cell in (orange_items | mid_items)
                         if cell not in wall_path and cell[1] <= 2
                         and cell not in steps_cards}
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
            step = shortest_action(info, player, {launch},
                                   allow_obstacles=False,
                                   )
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
        if direction != "right" and cell in suspect_cells:
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
        path = [(player[0], col)
                for col in range(player[1] + 1, min(5, player[1] + 4))]
        path_pyramids = dash_path_pyramids(info, *player)
        # A visible wall of three outranks a pair even while its detection
        # is still stabilizing (hunt_walls False): the instant pair dash was
        # firing first and spent the dash on 2 pyramids while a 3-wall sat
        # one row away (long run 20260820T033221).
        full_wall = nearest_dash_wall(info, player, preview=preview)
        # Tickets are worth ~nothing: only energy and mid-tier pickups may
        # veto a dash over scroll loss.
        at_risk = {cell for cell in (orange_items | mid_items)
                   if cell not in path and cell[1] <= 2
                   and cell not in steps_cards}
        # A bare two-pyramid pair no longer justifies 400 shards: the true
        # alternative is the free two-step detour (80), not two garras
        # (run 20260821T225908 burned nine dashes with empty paths). The
        # pair pays only with an item in its path, a third pyramid, or a
        # right-side target the dash genuinely approaches.
        path_items = any(info[cell]["item"] > .06
                         or info[cell].get("claw", 0.0) > .10
                         for cell in path)
        # Payload only when the dash's own break opens the lane to the
        # target: three columns of pure advance cost three steps (120
        # shards) on foot against 400 for the dash, so an off-row
        # pickup at column 3+ never paid for it - yet it made every
        # bare pair fire, bypassing both the stock gate and the
        # preview-needs-payload rule (review 2026-08-22, 'economy').
        right_targets = any(cell[0] == player[0] and cell[1] >= 3
                            for cell in (orange_items | mid_items))
        # REFUTED 2026-08-28, by the runner's own dash_result records.
        # The rule here used to read "two REAL pyramids pay for the dash
        # on their own - each break drops at ~46% and the dash collects
        # its drops in the same motion", and fired a bare pair whenever
        # dash stock was comfortable. The second half of that sentence is
        # false, and the log had been saying so all along:
        #
        #   2 pyramids, no item in the path   n=427   +12.9 energy
        #   3 pyramids, no item in the path   n= 92   +20.7
        #   2 pyramids, an item in the path   n= 33  +108.5
        #
        # The median of a bare dash is exactly 20 - the passive tick,
        # which arrives whether or not anything is dashed. So a dash
        # collects what is ALREADY lying in its path (the 108.5 row is
        # real) and does NOT collect what the pyramids it breaks drop.
        # Two breaks at the measured 44% should have shown ~110; they
        # show the clock.
        #
        # Priced out: 400 shards buys three columns of advance, which on
        # foot is three steps (120). The pyramids only cost something
        # when there is no way around, and going around is two paws (80).
        # 427 of the 556 recorded dashes - 77% - were this bare pair:
        # 170,800 shards for the tick.
        #
        # So the pair is back to what this file said before the doctrine
        # was added: an item in the path, a third pyramid, or a same-row
        # target the dash genuinely approaches - plus the premise itself,
        # added 2026-08-28b after the user stopped a run over a garra:
        # "going around two pyramids is two paws" only holds while there
        # IS a way around. Run 20260828T185642 n=11 had pyramids above,
        # below and ahead, so the real alternatives were two garras (400,
        # no advance) or a walk back through column 0. Of 266 bare pairs
        # in the recordings, 227 (85%) do have the sidestep and stay
        # vetoed; 39 (15%) are walled like that one.
        #
        # The test lives in pair_dash_pays so the rule that WALKS to a
        # launch asks exactly this question too.
        pair_worth = pair_dash_pays(info, tuple(player),
                                    orange_items | mid_items)
        # One scroll from a wall of three: wait for it.
        #
        # The sixth column is a real reading, not a guess - it is the
        # sliver of column 5 the board shows past its own edge - and when
        # it lights up on the player's row, a pyramid enters at column 4
        # on the next scroll. If the pair already in the path sits at
        # columns 3 and 4, that scroll leaves BOTH of them inside the
        # path (they slide to 2 and 3) and drops the newcomer at 4: two
        # becomes three, for the price of the rightward step the bot was
        # going to take anyway.
        #
        # Run 20260828T213035 n=29 (user: "era claro que venia un
        # segmento de tres piramides y se hizo un dash antes de estar al
        # lado, entonces solo rompio dos de las tres"): player at (0,1),
        # pyramids at (0,3) and (0,4), preview lit on row 0. It spent 400
        # shards on two.
        #
        # Only when every path pyramid is at column 3 or more. One at
        # column 2 would slide to column 1 and OUT of the path, so
        # waiting would trade a pyramid for a pyramid and gain nothing.
        path_pyramid_cells = [cell for cell in path if is_obstacle(info[cell])]
        third_is_one_scroll_away = (
            preview is not None and preview[player[0]]
            and len(path_pyramid_cells) == 2
            and all(cell[1] >= 3 for cell in path_pyramid_cells))
        if third_is_one_scroll_away:
            pair_worth = False
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
                if dash_path_pyramids(info, *launch) < 2:
                    continue
                launch_path = {(launch[0], col)
                               for col in range(launch[1] + 1,
                                                min(5, launch[1] + 4))}
                launch_items = any(info[cell]["item"] > .06
                                   or info[cell].get("claw", 0.0) > .10
                                   for cell in launch_path)
                # Same gate as the pair itself: walking a paw to line
                # up a dash that loses 280 shards loses the paw too.
                #
                # Judged on the LAUNCH row, exactly like launch_risk
                # below. right_targets asks about the PLAYER's row, so
                # using it here justified climbing to row 3 with the
                # target sitting on row 4 - the launch fired, and from
                # the launch cell the orange won again and sent the bot
                # straight back (run 20260822T215547 n=27-28, caught by
                # the replay corpus when the stock gate stopped hiding
                # it).
                launch_targets = any(cell[0] == launch[0] and cell[1] >= 3
                                     for cell in (orange_items | mid_items))
                if not (launch_items or launch_targets
                        or dash_path_pyramids(info, *launch) >= 3):
                    continue
                launch_risk = {cell
                               for cell in (orange_items | mid_items)
                               if cell not in launch_path and cell[1] <= 2
                               and cell not in steps_cards}
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
    tour_mids = mid_items
    if mid_items:
        mid_types = {cell: pickup_type(info[cell]) for cell in mid_items}
        tour_mids = prune_low_value_mids(player, orange_items, mid_items,
                                         mid_types, info=info)
    tour_items = orange_items | tour_mids
    if tour_items:
        order = plan_tour(player, tour_items)
        if order:
            first = order[0]
            # Attack routing only pays toward oranges: a 200-shard
            # garra to reach a 130-200 shard card is a losing trade
            # (run 20260822T142042 n=82 broke a pyramid to reach a
            # steps card). A blocked card takes the free way around
            # or drops out of the plan.
            routed = shortest_action(info, player, {first},
                                     allow_obstacles=(attacks_enabled
                                                      and first in orange_items),
                                     prefer_direction=previous_direction,
                                     protect=order[1:],
                                     
                                     with_cost=True)
            if routed:
                target, obstacle, direction = routed[0]
                # The label names the FIRST target's real category: every
                # mid-tier pickup used to print as "claw", and the user
                # read a steps-card chase as a garra spent on nothing
                # (run 20260822T142042 n=499).
                if first[1] == 0:
                    label = ("orange perishable" if first in orange_items
                             else "urgent pickup")
                elif first in orange_items:
                    label = "orange"
                else:
                    label = pickup_type(info[first]) or "pickup"
                return ("attack" if obstacle else "move", target, direction), \
                    f"{label} targets={order}"
            # (The 'tour boxed by suspects' wait retired 2026-08-23:
            # suspicion no longer severs routes, so there is nothing to
            # wait out. A route can now only be cut by a pyramid, and
            # waiting never removes one.)

    # Tickets remain as a last-resort target - never worth a garra.
    # Mid-tier cards are excluded here: a card the pruner judged not
    # worth its walk must not sneak back in as a "ticket" (run
    # 20260822T153206 n=53 chased the pruned steps card this way).
    ticket_goals = other_items - mid_items
    if ticket_goals:
        step = shortest_action(info, player, ticket_goals,
                               allow_obstacles=False,
                               prefer_direction=previous_direction,
                               )
        if step:
            target, obstacle, direction = step
            return ("attack" if obstacle else "move", target, direction), \
                f"item targets={sorted(ticket_goals)}"

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
        corridor_risk = {cell for cell in (orange_items | mid_items)
                         if cell not in dash_row and cell[1] <= 2}
        if not corridor_risk:
            return ("dash", player, "right"), \
                f"{right_obstacles} consecutive right obstacles"

    # Fast exploration: keep moving right. If blocked, destroy the obstacle;
    # if at an edge, choose a highlighted orthogonal neighbor without reversing.
    # Incoming-wall rows (user directive 2026-08-22): a pyramid visible
    # at (r,4) with the sixth-column preview lit on the same row is a
    # wall ENTERING row r - two independent confirmations. Align to
    # that row before scrolling: vertical steps do not move the world,
    # so the wall stands still while the bot positions for the launch
    # (run 20260822T215547 paid 2 walk-back taps by scrolling from the
    # wrong row while the wall came in).
    incoming_rows = ([r for r in range(5)
                      if preview[r] and is_obstacle(info[(r, 4)])]
                     if preview is not None else [])
    # Forming wall with its LEFT side already in place: a partial run
    # touching columns 1-2 on a row with reinforcements incoming
    # ((r,4) pyramid or preview lit). Physics: pyramids only enter
    # when the bot scrolls, and every scroll also EATS the left side
    # of that run - run 20260822T234822 n=14 scrolled 3 times and
    # expelled its own (4,1),(4,2) unbroken. The right play is to walk
    # to the launch and pair-dash what is already there: the dash's
    # own 3-column scroll pulls the reinforcements in for the next
    # wall. Route to the launch instead of exploring.
    if preview is not None:
        for r in range(5):
            reinforced = preview[r] or is_obstacle(info[(r, 4)])
            if not reinforced:
                continue
            start = next((c for c in range(5)
                          if is_obstacle(info[(r, c)])), None)
            # Only a wall whose left side is ALREADY at column 1.
            #
            # This rule exists to save a wall the next scroll would eat:
            # run 20260822T234822 n=14 had (4,1),(4,2) in position plus
            # (4,4) and the preview lit, and the explorer scrolled three
            # times and expelled its own left side unbroken. A run that
            # starts at column 2 is not in that danger - scrolling
            # brings it closer, not to its death - so walking to its
            # launch buys nothing the belt would not give for free.
            #
            # And walking there costs plenty. Run 20260828T211315
            # n=32-38 (user: "otra vez empezo a dar vueltas"): row 2
            # held a pair starting at column 2, this rule walked the bot
            # to the launch, the pair rule refused on arrival, explore
            # walked it off, and this sent it back. Seven paws on a
            # board that never changed.
            if start != 1:
                continue
            run_len = 0
            while start + run_len < 5 and is_obstacle(info[(r, start + run_len)]):
                run_len += 1
            if run_len < 2:
                continue
            launch = (r, start - 1)
            # Positioning must share the predicate that will FIRE the
            # dash on arrival, or the walk is pure loss and explore eats
            # the wall anyway (review 2026-08-22, 'conflicts' lens).
            #
            # It stopped sharing it on 2026-08-28, when the bare-pair
            # veto was rewritten and this line was left quoting the old
            # dash-stock gate. Run 20260828T211315 n=32-38: row 2 held a
            # two-pyramid pair, stock was full, so this walked the bot to
            # the launch - and the pair rule, which now asks about items,
            # same-row targets and whether there is a way around,
            # refused. Explore took over, walked it off, and this sent it
            # back. Seven paws on a board that never changed.
            #
            # The promised pyramid counts, because saving the wall is
            # the whole point and by arrival it will have landed. That
            # anticipation is exactly why this rule may only look at
            # walls already touching column 1: elsewhere it would walk
            # toward a dash the arrival board does not justify, which is
            # the disagreement the 211315 loop was made of.
            #
            # No anticipation at all, from either half of `reinforced`.
            # Walking to a column-0 launch does not scroll - left, up
            # and down never do - so the board on arrival is the board
            # right here, and neither the pyramid already standing at
            # column 4 nor the one the preview promises at column 5 is
            # inside the dash path, which reaches columns 1-3.
            #
            # Counting either of them broke the rule this comment block
            # already states: positioning must share the predicate that
            # FIRES the dash. Run 20260828T215949 n=78 was the column-4
            # half (two paws backwards), and run 20260828T233043
            # n=79-85 was the preview half, which cost more: row 1 held
            # (1,1),(1,2) with the preview lit and row 2 wide open, so
            # this walked the bot two paws to (1,0), the pair rule
            # refused on arrival because a bare pair with a way around
            # is not worth 400 shards, explore walked it off, this sent
            # it back, and it finally spent a GARRA on (1,1) and dashed
            # from inside the wall anyway (user: "lo mas facil hubiera
            # sido usar una garra... pero en vez de usar un dash, uso
            # garras").
            #
            # What survives is the routing: when the pair on the board
            # pays by itself, this still walks to its launch instead of
            # scrolling it away. What is gone is walking toward a dash
            # the arrival board does not justify.
            if not (dashes_enabled
                    and pair_dash_pays(info, launch,
                                       orange_items | mid_items)):
                continue
            if tuple(player) == launch:
                break
            step = shortest_action(info, player, {launch},
                                   allow_obstacles=False,
                                   prefer_direction=previous_direction,
                                   )
            if step:
                target, obstacle, direction = step
                return ("move", target, direction), \
                    f"position for forming wall at {launch}"
    # Refusing to advance protects a column-0 prize only if the prize can
    # still be taken: a perishable walled off from the player is lost
    # whatever we do, and standing still to mourn it burns paws for
    # nothing (run 20260823T074036 n=197-199 ping-ponged (0,0)<->(0,1) to
    # the end of the run over a dash orb behind a two-pyramid wall).
    # allow_obstacles=False on purpose: a garra to rescue one orange is
    # a marginal trade, not a rescue - 200 shards is about 91 energy at
    # the measured 18.2 energy per 40-shard step, against the orange's
    # 125 - and marginal is not enough to hold the whole world still on
    # its behalf, so a perishable reachable only by breaking through
    # does not veto the advance either.
    # tour_items, not the raw sightings: the veto and the plan must want
    # the same things. Reading orange_items | mid_items let a pickup the
    # tour had already pruned as not worth a detour still hold the whole
    # world still on its behalf - two mechanisms disagreeing about what
    # is worth protecting, which is the shape of bug this bot keeps
    # growing (docs/review-2026-08-22.md).
    gettable_perishables = any(
        shortest_action(info, player, {cell}, allow_obstacles=False)
        is not None
        for cell in tour_items if cell[1] == 0)
    # Can the belt be advanced at all without breaking something? Column 2
    # is the cell a step must enter to scroll, so the explorer is BOXED
    # when no free route reaches an unobstructed one. Asking it as a
    # reachability FACT rather than looking one row up and down is what
    # separates the two cases that look identical from a single cell: a
    # sealed row can be the CORRIDOR to a free one (two paws, 80 shards,
    # cheaper than the garra) or the last row before the edge (run
    # 20260822T184638 n=66-67 stepped down into one and back up, two paws
    # for nothing, and was still boxed).
    advance_cells = {(row, 2) for row in range(5)
                     if not is_obstacle(info[(row, 2)])}
    boxed = (not advance_cells
             or shortest_action(info, player, advance_cells,
                                allow_obstacles=False) is None)
    candidates = []
    for dr, dc, direction in DIRS:
        nxt = (player[0]+dr, player[1]+dc)
        if not (0 <= nxt[0] < 5 and 0 <= nxt[1] < 5):
            continue
        v = info[nxt]
        obstacle = is_obstacle(v)
        if obstacle and not attacks_enabled:
            continue
        if obstacle and (direction == "left" or suspect_cells):
            # The world itself moves left: a left pyramid never needs
            # breaking (run 20260822T160202 n=72 spent 200 shards
            # exploring backwards). And while suspects block the
            # alternatives, no explore garra in ANY direction: run
            # 20260822T184638 n=41 attacked the pyramid ABOVE just
            # because post-pickup confetti boxed it in - a frame of
            # waiting clears the suspects for free.
            continue
        if direction == "left" and suspect_cells:
            # Same law for the plain left step: while suspects block
            # the alternatives, waiting a frame beats walking backward
            # (run 20260822T183056 n=14 stepped left for nothing). A
            # genuinely cornered explorer - real pyramids, no suspects
            # - may still escape left.
            continue
        if direction == "right" and nxt[1] >= 2 and gettable_perishables:
            # The scroll budget is an invariant of the whole decision,
            # not of the tour branch: when the tour cannot route to a
            # column-0 pickup, falling through to explore used to
            # scroll the very perishable the budget was protecting off
            # the board (review 2026-08-22, 'conflicts' lens).
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
            if boxed:
                # Nowhere to walk to: sink the step below the forward
                # garra (5 + highlight). Shuffling only delays the 200
                # shards, and the two paws it burns are not free either.
                score -= 20
            elif dash_path_pyramids(info, nxt[0], nxt[1]) >= 2:
                # Only a row that could actually LAUNCH a pair is worth
                # a curiosity step, which is the same threshold the
                # pair-launch rule enforces. Counting scattered
                # obstacles instead rewarded a row whose single pyramid
                # was the forward blocker itself: run 20260823T151854
                # n=13-15 climbed to (0,1) for the pyramid at (0,2),
                # found the way forward closed by it, and walked back
                # down two rows to a lane that was free all along.
                score += 6 * dash_path_pyramids(info, nxt[0], nxt[1])
            else:
                # No pair to hunt there, so the only thing a vertical
                # step buys is a lane that goes forward; "down"
                # outbidding "up" by base score alone picked walled rows
                # on merit (run 20260823T153436 n=3-5: (3,1) walled by
                # (3,2) stepped down to (4,1) walled by (4,2) and came
                # straight back; same shape at n=29-30 of
                # 20260823T151420). Eight points break the tie between
                # boring lanes and never outbid an item, a wall or a
                # dash.
                score += 8 if not is_obstacle(info[(nxt[0], 2)]) else -8
            # Alignment toward an incoming wall beats scrolling from
            # the wrong row: the step that closes distance to the
            # nearest incoming row outbids the plain right (100).
            if incoming_rows and not obstacle:
                closes = min(abs(nxt[0] - r) for r in incoming_rows) < \
                    min(abs(player[0] - r) for r in incoming_rows)
                if closes:
                    score += 120
        if nxt in barren_cells:
            # Standing here already, with the belt where it is now and
            # nothing collected since, produced whatever the planner is
            # about to decide again. Measured over every recording: 351
            # of 3062 cell changes are that exact return - 351 paws, some
            # 6400 energy - and 125 of 1346 vertical steps are reversed
            # on the very next frame with the belt unmoved.
            #
            # All THREE terms are the rule. A plain "we were here" would
            # also punish the 1279 returns that DID collect something,
            # which is the round trip measured as worth 125 for 36 - the
            # veto retired on 2026-08-28 wearing a new hat. The runner
            # clears this memory the moment the belt moves or a pickup
            # lands, so a cell only stays barren while the world does.
            #
            # A penalty, never a ban: in a cul-de-sac the only legal move
            # IS back, and `pool = preferred or candidates` below is what
            # keeps a fully penalised board from stalling. 60 outbids the
            # lane tie-break (8), the pair curiosity (6 per pyramid) and
            # the gap between up and down, but never the plain advance
            # (100), which the belt makes self-clearing anyway.
            score -= 60
        if previous_direction and {previous_direction, direction} in ({"left","right"},{"up","down"}):
            score -= 30
        candidates.append((score, nxt, obstacle, direction,
                           boxed and direction in ("up", "down")))
    if not candidates:
        return None, "no orthogonal candidate"
    # Cells banned by the loop breaker are avoided while any alternative
    # exists; falling back to them beats stalling in a fully banned pocket.
    # Cells the loop breaker banned are avoided; SUSPECT cells are not.
    # ignored_targets carries both, and treating the suspects in it as
    # terrain brought back the pathology retired from this very function
    # on 2026-08-23: run 20260823T074036 n=155 stepped BACKWARD to (0,1)
    # because the free step down happened to land on a one-frame
    # suspect. Walking onto a maybe-item is free - it either collects
    # something or nothing - so it can cost a goal, never a route.
    avoided = ignored - set(suspect_cells)
    preferred = [entry for entry in candidates if entry[1] not in avoided]
    # (The suspect filter and the 'boxed by suspects' wait retired
    # 2026-08-23: a confetti card is ground, not a wall, so there is
    # nothing to be boxed by. A pyramid hidden UNDER confetti keeps its
    # own track in the world model and is refused as the pyramid it is.)
    pool = preferred or candidates
    # A garra never outbids a free step that advances or flanks
    # (up/down/right). Run 20260822T215547 n=47: the anti-reverse
    # hysteresis (-30) sank the free step up below the attack's score
    # and bought a 200-shard garra beside a free move. The left escape
    # does not count as an alternative: it buys no progress, so a
    # truly cornered explorer (only left open) still breaks forward.
    # Neither does a vertical step while BOXED - no row the player can
    # reach can advance the belt - for the same reason: shuffling between
    # sealed rows is not cheaper than the garra that opens the way, it is
    # just quieter (run 20260822T184638 n=66-67).
    movers = [entry for entry in pool
              if not entry[2] and entry[3] != "left" and not entry[4]]
    _, target, obstacle, direction, _ = max(movers or pool)
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
        print(f"ERROR: {exc}", file=sys.stderr)
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
