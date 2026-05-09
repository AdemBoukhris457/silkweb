from __future__ import annotations

import asyncio
import math
import random
from typing import Any


def _bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    """
    Cubic Bezier interpolation.
    """
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t
    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)


async def human_mouse_move(page: Any, target_selector: str) -> None:
    """
    Move mouse to the center of `target_selector` using a Bezier-curve path.
    Best-effort: does nothing if selector can't be found.
    """
    try:
        el = await page.query_selector(target_selector)
        if el is None:
            return
        box = await el.bounding_box()
        if not box:
            return
    except Exception:
        return

    tx = float(box["x"] + box["width"] / 2.0)
    ty = float(box["y"] + box["height"] / 2.0)

    # We don't have a reliable "current mouse position" API; start near the target with some randomness.
    sx = max(1.0, tx + random.uniform(-200.0, 200.0))
    sy = max(1.0, ty + random.uniform(-200.0, 200.0))

    dx = tx - sx
    dy = ty - sy
    dist = math.hypot(dx, dy)
    steps = int(min(80, max(18, dist / 10.0)))

    # Control points offset perpendicular to direction.
    nx = -dy / dist if dist else 0.0
    ny = dx / dist if dist else 0.0
    c1 = (
        sx + dx * 0.25 + nx * random.uniform(-80.0, 80.0),
        sy + dy * 0.25 + ny * random.uniform(-80.0, 80.0),
    )
    c2 = (
        sx + dx * 0.75 + nx * random.uniform(-80.0, 80.0),
        sy + dy * 0.75 + ny * random.uniform(-80.0, 80.0),
    )

    try:
        # Jump to starting point first (without many intermediate moves).
        await page.mouse.move(sx, sy)
        for i in range(1, steps + 1):
            t = i / steps
            x, y = _bezier((sx, sy), c1, c2, (tx, ty), t)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.004, 0.02))
    except Exception:
        return


async def human_type(page: Any, selector: str, text: str) -> None:
    """
    Type into an element with per-character delays and occasional backspace+retype.
    Best-effort: no-op if selector can't be focused.
    """
    try:
        await page.focus(selector)
    except Exception:
        return

    for ch in text:
        try:
            await page.keyboard.type(ch)
        except Exception:
            return
        await asyncio.sleep(random.uniform(0.05, 0.2))

        # 2% chance: backspace and retype this char
        if random.random() < 0.02:
            try:
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await page.keyboard.type(ch)
            except Exception:
                return
            await asyncio.sleep(random.uniform(0.05, 0.2))


async def random_scroll(page: Any, *, max_steps: int = 6) -> None:
    """
    Scroll down in random increments with random pauses, simulating reading.
    """
    steps = random.randint(2, max(2, int(max_steps)))
    for _ in range(steps):
        delta = random.randint(180, 900)
        pause = random.uniform(0.15, 1.2)
        try:
            await page.mouse.wheel(0, delta)
        except Exception:
            try:
                await page.evaluate("(d) => window.scrollBy(0, d)", delta)
            except Exception:
                return
        await asyncio.sleep(pause)
