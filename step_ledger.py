"""What the game charged us, and what that means for the world.

The 5x5 grid is furniture: it never moves. Its CONTENTS ride a conveyor
belt that runs right to left, and the belt advances exactly one column
when a step carries the player from column 1 into column 2. Nothing else
moves the world - not a vertical step, not a left step, not an attack.

That makes "did my tap land?" a bookkeeping question rather than a vision
one: the game charges a pink paw for every step it takes, and the HUD
counter is legible on 100% of recorded frames (run 20260823T074036,
150/150). So the runner stops inferring the scroll from pixels and simply
confirms the charge - the user's doctrine, 2026-08-23:

    "si el movimiento es exitoso (se consume una patica rosada) de
     columna 1 a 2 el mundo se debera correr uno a la izquierda
     (contenidos) y la verificacion deberia ser solo confirmar que dicho
     movimiento se dio."

Taps are taken in order, so a batch the game froze halfway through took
its FIRST k taps (same run #8: two taps, one paw, player on the first
target). Every reader here follows that rule.
"""

BOARD = 5
#: A steps card refunds five paws. Measured on run 20260823T074036 frames
#: #10 and #55: one step onto a card, counter +4 net, player moved.
STEPS_CARD_BONUS = 5


def move_taps(sent):
    """How many of these taps cost a paw. Attacks and dashes cost none."""
    return sum(1 for tap in sent if tap.get("type") == "move")


def charged_steps(before, after, taps, bonus=STEPS_CARD_BONUS):
    """How many of `taps` move taps the game actually charged, or None.

    A steps card collected on the way refunds `bonus` paws, so the raw
    counter delta is `charged - bonus * cards`. The caller does not have
    to know a card landed: with the batches this runner sends (three taps
    at most) exactly one card count can satisfy the arithmetic, so the
    ledger solves for it and refuses whenever it cannot.

    None means the counters cannot answer - unreadable HUD, or a reading
    no single frame could produce (a misread digit turned 3644 into 3 on
    run 20260823T074036 #11). The caller then falls back to the pixel
    sensor. None never means "assume zero".
    """
    if before is None or after is None:
        return None
    delta = before - after
    fits = [delta + bonus * cards for cards in range(3)
            if 0 <= delta + bonus * cards <= taps]
    return fits[0] if len(fits) == 1 else None


def sane_reading(previous, reading, taps, bonus=STEPS_CARD_BONUS):
    """The counter as read, or None when no single frame could explain it.

    Refusing the READING rather than only the arithmetic matters: a bad
    digit kept as the reference would make the NEXT delta implausible
    too, costing two frames instead of one (run 20260823T074036 #11-#12).
    """
    if reading is None or previous is None:
        return reading
    return reading if abs(reading - previous) <= taps + 3 * bonus else None


def _walk(sent, charged):
    """Yield the taps the game took, in order, with their kind."""
    for tap in sent:
        if tap.get("type") != "move":
            continue                      # costs no paw, takes no charge
        if charged <= 0:
            return                        # the game froze here
        charged -= 1
        yield tap


def scrolls(tap):
    """A right step into screen column >= 2 - the only belt advance."""
    target = tap.get("target_cell") or ()
    return (tap.get("direction") == "right" and len(target) == 2
            and target[1] >= 2)


def conveyor_shift(sent, charged):
    """Columns the world slid left because of these taps."""
    return sum(1 for tap in _walk(sent, charged) if scrolls(tap))


def charge_matching_shift(sent, columns):
    """How many taps the game took, deduced from a measured scroll.

    The fallback slot behind the receipt. It answers only when the
    measurement is decisive: a still world says nothing about a batch of
    vertical steps, which move no belt whether they landed or not.
    """
    if columns is None:
        return None
    fits = [k for k in range(move_taps(sent) + 1)
            if conveyor_shift(sent, k) == columns]
    return fits[0] if len(fits) == 1 else None


def refused_tap(sent, charged):
    """The first move tap the game did not take, or None.

    A tap that cost no paw did not happen: the game either refused it
    ("cannot move there" on an undetected wall) or swallowed it under
    load. The two look identical here on purpose - the caller replans
    from a state it KNOWS is unchanged, and only blames the cell when the
    same target comes back refused.
    """
    if charged is None:
        return None
    for tap in sent:
        if tap.get("type") != "move":
            continue
        if charged <= 0:
            return tuple(tap["target_cell"])
        charged -= 1
    return None


def landing(sent, charged, player):
    """Where the player stands once the game has taken `charged` taps.

    A scroll step ends where it began in board coordinates: the player
    walks one column right and the world immediately slides one column
    left underneath.
    """
    cell = tuple(player)
    for tap in _walk(sent, charged):
        row, col = tap["target_cell"]
        cell = (row, col - 1) if scrolls(tap) else (row, col)
    return cell
