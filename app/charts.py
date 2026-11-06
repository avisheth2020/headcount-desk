"""Chart geometry. Pure functions, no database and no HTML, so each is easy to test.

The markup lives in templates/_charts.html. Charts are drawn on the server as
SVG or plain boxes: the Content Security Policy allows no inline scripts and the
design system allows no chart library.
"""

VARIANCE_LOW, VARIANCE_HIGH = 95.0, 105.0        # the scale of a budget variance bar, centered on 100%


def sparkline(values: list, width: int = 96, height: int = 28, pad: float = 3.0) -> dict | None:
    """The path of a small trend line. None if there is nothing to draw."""
    points = [float(v) for v in values if v is not None]
    if len(points) < 2:
        return None
    low, high = min(points), max(points)
    spread = (high - low) or 1.0
    xs = [pad + i * (width - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [height - pad - (v - low) / spread * (height - 2 * pad) for v in points]
    line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    return {"line": line, "area": f"{line} L{xs[-1]:.1f} {height} L{xs[0]:.1f} {height} Z",
            "x": round(xs[-1], 1), "y": round(ys[-1], 1), "width": width, "height": height,
            "first": points[0], "last": points[-1]}


def variance(pct) -> dict | None:
    """Where a percent-of-budget bar sits on a scale centered on 100%.
    Returns its left edge and width in percent of the track. `clipped` means the
    real value is past the end of the scale; the number beside the bar stays exact."""
    if pct is None:
        return None
    value = float(pct)
    shown = min(max(value, VARIANCE_LOW), VARIANCE_HIGH)
    span = VARIANCE_HIGH - VARIANCE_LOW
    position = (shown - VARIANCE_LOW) / span * 100
    center = (100 - VARIANCE_LOW) / span * 100
    return {"left": round(min(position, center), 2), "width": round(abs(position - center), 2),
            "over": value > 100, "clipped": value != shown}


def share_bars(rows: list[dict], key: str) -> list[dict]:
    """Rows with a bar width in percent of the largest value, largest first."""
    top = max((max(r[key], 0) for r in rows), default=0) or 1
    ordered = sorted(rows, key=lambda r: -r[key])
    return [{**r, "bar": round(max(r[key], 0) / top * 100, 1)} for r in ordered]
