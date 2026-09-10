"""Server-rendered inline SVG charts.

No chart library and no CDN: the dashboard has to work on an isolated plant
network. Quantities only - nothing here plots money.

Palette: categorical slots 1 (blue) and 2 (orange) from the validated default
data-viz palette; single-series bars use the sequential blue ramp. The two-hue
pair was checked with the palette validator (CVD dE 24.7, normal-vision 33.6,
both >= 3:1 on white) before being used here.
"""
from decimal import Decimal
from html import escape

SERIES_1 = "#2a78d6"   # categorical slot 1 - blue   (inward)
SERIES_2 = "#eb6834"   # categorical slot 2 - orange (outward)
SEQ_BLUE = "#2a78d6"
INK = "#16202e"
INK_2 = "#4a5768"
INK_3 = "#78859a"
GRID = "#e4e9f0"


def _n(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _fmt(value):
    v = _n(value)
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _nice_max(value):
    """Round the axis top up to a readable number."""
    value = _n(value)
    if value <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for mult in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= base * mult:
            return base * mult
    return base * 10


def _ticks(top, count=4):
    return [top * i / count for i in range(count + 1)]


def grouped_bar_chart(labels, series, *, height=210, width=680, unit="",
                      empty_text="No movement recorded for this period."):
    """Vertical grouped bars. `series` = [(name, colour, [values...]), ...].

    Used for monthly inward vs outward quantity (two series, one y-axis).
    """
    labels = list(labels)
    if not labels or not series or not any(any(v for v in s[2]) for s in series):
        return f'<div class="empty"><strong>Nothing to chart yet</strong>{escape(empty_text)}</div>'

    pad_l, pad_r, pad_t, pad_b = 46, 8, 12, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    top = _nice_max(max(_n(v) for _n_, _c, vals in series for v in vals))

    group_w = plot_w / len(labels)
    n = len(series)
    gap = 2.0                                   # 2px surface gap between bars
    bar_w = max(4.0, min(20.0, (group_w * 0.62 - gap * (n - 1)) / n))
    radius = min(4.0, bar_w / 2)

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'preserveAspectRatio="xMidYMid meet">']

    for t in _ticks(top):
        y = pad_t + plot_h - (t / top) * plot_h
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 7}" y="{y + 3.5:.1f}" text-anchor="end" '
                   f'font-size="10" fill="{INK_3}" font-family="ui-monospace,monospace">'
                   f'{_fmt(t)}</text>')

    for gi, label in enumerate(labels):
        gx = pad_l + gi * group_w
        cluster_w = bar_w * n + gap * (n - 1)
        x0 = gx + (group_w - cluster_w) / 2
        for si, (name, colour, values) in enumerate(series):
            val = _n(values[gi]) if gi < len(values) else 0.0
            h = (val / top) * plot_h if top else 0
            x = x0 + si * (bar_w + gap)
            y = pad_t + plot_h - h
            if h <= 0:
                continue
            r = min(radius, h)
            out.append(
                f'<path d="M{x:.1f},{pad_t + plot_h:.1f} V{y + r:.1f} '
                f'Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
                f'H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f} '
                f'V{pad_t + plot_h:.1f} Z" fill="{colour}">'
                f'<title>{escape(str(label))} &middot; {escape(name)}: '
                f'{_fmt(val)} {escape(unit)}</title></path>')
        out.append(f'<text x="{gx + group_w / 2:.1f}" y="{height - 10}" text-anchor="middle" '
                   f'font-size="10.5" fill="{INK_2}">{escape(str(label))}</text>')

    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" '
               f'y2="{pad_t + plot_h}" stroke="#c2ccd8" stroke-width="1"/>')
    out.append("</svg>")

    legend = '<div class="chart-legend">' + "".join(
        f'<span><i style="background:{c}"></i>{escape(nm)}</span>' for nm, c, _v in series
    ) + "</div>"
    return "".join(out) + legend


def horizontal_bar_chart(rows, *, unit="", width=680, bar_h=22, colour=SEQ_BLUE,
                         empty_text="No stock recorded yet.", max_rows=10,
                         label_width=170):
    """Horizontal bars for ranked categories - one series, so no legend box.

    `rows` = [(label, value), ...]. Values are direct-labelled at the bar end,
    which is the relief for any low-contrast fill.
    """
    rows = [(str(a), _n(b)) for a, b in rows if _n(b) > 0][:max_rows]
    if not rows:
        return f'<div class="empty"><strong>Nothing to chart yet</strong>{escape(empty_text)}</div>'

    gap = 8
    pad_t, pad_b, pad_r = 4, 4, 62
    height = pad_t + pad_b + len(rows) * (bar_h + gap) - gap
    plot_w = width - label_width - pad_r
    top = _nice_max(max(v for _l, v in rows))
    radius = 4

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
           f'preserveAspectRatio="xMidYMid meet">']
    for i, (label, value) in enumerate(rows):
        y = pad_t + i * (bar_h + gap)
        w = max(2.0, (value / top) * plot_w)
        short = label if len(label) <= 30 else label[:29] + "…"
        out.append(f'<text x="{label_width - 10}" y="{y + bar_h / 2 + 4:.1f}" '
                   f'text-anchor="end" font-size="11.5" fill="{INK}">{escape(short)}'
                   f'<title>{escape(label)}</title></text>')
        r = min(radius, w)
        out.append(
            f'<path d="M{label_width},{y} H{label_width + w - r:.1f} '
            f'Q{label_width + w:.1f},{y} {label_width + w:.1f},{y + r:.1f} '
            f'V{y + bar_h - r:.1f} Q{label_width + w:.1f},{y + bar_h} '
            f'{label_width + w - r:.1f},{y + bar_h} H{label_width} Z" fill="{colour}">'
            f'<title>{escape(label)}: {_fmt(value)} {escape(unit)}</title></path>')
        out.append(f'<text x="{label_width + w + 8:.1f}" y="{y + bar_h / 2 + 4:.1f}" '
                   f'font-size="11.5" fill="{INK_2}" font-family="ui-monospace,monospace">'
                   f'{_fmt(value)}</text>')
    out.append("</svg>")
    return "".join(out)
