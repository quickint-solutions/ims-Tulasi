from datetime import date, datetime

from django.utils import timezone


def parse_date(value, default=None):
    if not value:
        return default
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return default


def month_start(d=None):
    d = d or timezone.localdate()
    return d.replace(day=1)


def add_months(d, months):
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def last_n_months(n=12, end=None):
    """[(date_first_of_month, 'Mon YY'), ...] oldest first."""
    end = month_start(end)
    out = []
    for i in range(n - 1, -1, -1):
        m = add_months(end, -i)
        out.append((m, m.strftime("%b %y")))
    return out


def financial_year_bounds(year):
    """Indian FY: 1 April year -> 31 March year+1."""
    return date(year, 4, 1), date(year + 1, 3, 31)


def suggest_document_number(model, prefix):
    """Suggest the next number. Purely advisory - the user may overwrite it
    and no yearly numbering is ever forced (sections 8, 35)."""
    if not prefix:
        return ""
    latest = (model.objects.filter(document_number__startswith=prefix)
              .order_by("-id").values_list("document_number", flat=True).first())
    seq = 1
    if latest:
        tail = latest[len(prefix):]
        digits = "".join(ch for ch in tail if ch.isdigit())
        if digits:
            seq = int(digits) + 1
    width = max(3, len(str(seq)))
    return f"{prefix}{seq:0{width}d}"
