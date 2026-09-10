"""Turns items into label render dictionaries for the 50 x 25 mm template."""
from .generators import cached_barcode_svg, cached_qr_svg
from .models import LabelTemplate


def label_context(item, request=None, template=None):
    template = template or LabelTemplate.get_default()
    show_qr = template.show_qr if template else True
    show_barcode = template.show_barcode if template else True
    max_chars = template.item_name_max_chars if template else 42
    hint = template.scan_hint_text if template else "SCAN TO VIEW PRODUCT DETAILS"

    balance = (item.stock_balances.filter(quantity__gt=0)
               .select_related("location").order_by("-quantity").first())
    return {
        "item": item,
        "template": template,
        "qr_svg": cached_qr_svg(item.public_url(request)) if show_qr else "",
        "barcode_svg": (cached_barcode_svg(item.barcode_number, module_width=0.22,
                                           module_height=9.0)
                        if show_barcode else ""),
        "name_is_long": len(item.name) > max_chars,
        "scan_hint": hint,
        "show_qr": show_qr,
        "show_barcode": show_barcode,
        "show_item_number": template.show_item_number if template else True,
        "show_item_name": template.show_item_name if template else True,
        "show_scan_hint": template.show_scan_hint if template else True,
        "show_location": template.show_location if template else False,
        "location_code": balance.location.code if balance else "",
    }
