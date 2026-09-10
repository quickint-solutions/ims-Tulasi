"""Barcode and QR image generation.

Libraries (all open source, see docs/LIBRARIES.md):
  python-barcode  https://github.com/WhyNotHugo/python-barcode   (MIT)
  qrcode          https://github.com/lincolnloop/python-qrcode   (BSD)
"""
import base64
import re
from io import BytesIO

import barcode
import qrcode
from barcode.writer import ImageWriter, SVGWriter
from django.core.cache import cache
from qrcode.image.svg import SvgPathImage

CODE128 = "code128"


def _data_uri(buffer, mime):
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def barcode_svg(value, *, module_width=0.22, module_height=9.0, font_size=0,
                quiet_zone=1.0, write_text=False):
    """Code 128 barcode as inline SVG markup, sized in millimetres."""
    writer = SVGWriter()
    buf = BytesIO()
    barcode.get(CODE128, str(value), writer=writer).write(buf, options={
        "module_width": module_width,
        "module_height": module_height,
        "font_size": font_size,
        "text_distance": 1,
        "quiet_zone": quiet_zone,
        "write_text": write_text,
    })
    return _responsive_svg(buf.getvalue().decode("utf-8"))


# Matches a coordinate given in millimetres, e.g. x="12.500mm".
_MM_VALUE = re.compile(r'="(\d+(?:\.\d+)?)mm"')


def _responsive_svg(svg):
    """Replace the fixed mm canvas with a viewBox so CSS can scale the graphic.

    python-barcode emits an SVG sized in millimetres whose bars are ALSO positioned
    in millimetres (x="1.000mm"). A viewBox is unitless, so the two must be put on
    the same scale or the bars are laid out 3.78x too wide and everything past the
    first quarter of the symbol falls outside the canvas - producing a barcode that
    looks plausible but is truncated and unscannable. Dropping the `mm` suffix from
    the bar coordinates makes one user unit equal one millimetre, which is exactly
    what the viewBox then describes.
    """
    start = svg.find("<svg")
    if start != -1:
        svg = svg[start:]

    if "viewBox" not in svg:
        m = re.search(r'width="([\d.]+)mm"\s+height="([\d.]+)mm"', svg)
        if m:
            w, h = float(m.group(1)), float(m.group(2))
            svg = svg.replace(m.group(0),
                              f'viewBox="0 0 {w} {h}" preserveAspectRatio="none"', 1)
            svg = _MM_VALUE.sub(r'="\1"', svg)
    else:
        svg = re.sub(r'\swidth="[^"]*"', "", svg, count=1)
        svg = re.sub(r'\sheight="[^"]*"', "", svg, count=1)
    return svg


def barcode_png_data_uri(value, *, module_width=0.3, module_height=12.0, write_text=True,
                         font_size=8, quiet_zone=2.0):
    """Code 128 barcode as a PNG data URI - used where SVG is awkward to print."""
    buf = BytesIO()
    barcode.get(CODE128, str(value), writer=ImageWriter()).write(buf, options={
        "module_width": module_width,
        "module_height": module_height,
        "write_text": write_text,
        "font_size": font_size,
        "text_distance": 3,
        "quiet_zone": quiet_zone,
        "dpi": 300,
    })
    return _data_uri(buf, "image/png")


def qr_svg(data, *, box_size=10, border=0, error_correction=qrcode.constants.ERROR_CORRECT_M):
    """QR code as inline SVG markup."""
    qr = qrcode.QRCode(version=None, error_correction=error_correction,
                       box_size=box_size, border=border, image_factory=SvgPathImage)
    qr.add_data(str(data))
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image().save(buf)
    return _responsive_svg(buf.getvalue().decode("utf-8"))


def qr_png_data_uri(data, *, box_size=8, border=1):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=box_size, border=border)
    qr.add_data(str(data))
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return _data_uri(buf, "image/png")


def cached_barcode_svg(value, **kwargs):
    key = f"bc:{value}:{hash(frozenset(kwargs.items()))}"
    svg = cache.get(key)
    if svg is None:
        svg = barcode_svg(value, **kwargs)
        cache.set(key, svg, 60 * 60 * 12)
    return svg


def cached_qr_svg(data, **kwargs):
    key = f"qr:{data}:{hash(frozenset(kwargs.items()))}"
    svg = cache.get(key)
    if svg is None:
        svg = qr_svg(data, **kwargs)
        cache.set(key, svg, 60 * 60 * 12)
    return svg
