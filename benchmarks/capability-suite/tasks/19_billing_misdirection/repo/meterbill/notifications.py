"""Plain-text e-mail bodies for customers (billing notifications).

Four notices are built from objects the billing run already has:

* ``invoice_issued(invoice)``            from an Invoice
* ``payment_reminder(state)``            from a DunningState
* ``suspension_notice(state, customer)`` from a DunningState whose steps include ``suspend``
* ``usage_alert(fired, customer, metrics)`` from an alerts.Fired

Each returns a ``Notification(to, subject, body)``.  Bodies are built from
the string templates in ``TEMPLATES`` with ``str.format_map``; paragraphs are
wrapped at 72 columns (``WIDTH``) with ``textwrap`` and tables (the invoice
summary) are laid out by hand so they keep their alignment.  Output is
deterministic: nothing depends on the clock, the locale or dict ordering, so
a notification can be compared byte for byte in a test or a mail archive.

Money is printed with ``render.fmt.format_money``; this module never rounds.
"""

import textwrap
from dataclasses import dataclass

from .render.fmt import format_money, format_qty
from .timeutil import format_instant

WIDTH = 72
SIGNATURE = "Kettle Cloud Billing\nbilling@kettlecloud.example"

TEMPLATES = {
    "invoice_issued": (
        "Hello {name},\n"
        "\n"
        "Your invoice {number} for the period {period} has been issued. "
        "The amount due is {due_amount}, payable by {due_date}.\n"
        "\n"
        "{summary}\n"
        "\n"
        "{notes}"
        "If anything looks wrong, reply to this message and quote the "
        "invoice number.\n"
        "\n"
        "{signature}\n"),
    "payment_reminder": (
        "Hello {name},\n"
        "\n"
        "Our records show that invoice {invoice} for {amount} was due on "
        "{due_date} and is still unpaid. {reminder_line}\n"
        "\n"
        "{next_step}"
        "If you have already paid, please ignore this message.\n"
        "\n"
        "{signature}\n"),
    "suspension_notice": (
        "Hello {name},\n"
        "\n"
        "Because invoice {invoice} for {amount} (due {due_date}) remains "
        "unpaid, your Kettle Cloud account {customer_id} has been suspended "
        "as of {suspended_on}.\n"
        "\n"
        "Service resumes once the invoice is paid in full. {fee_line}\n"
        "\n"
        "{signature}\n"),
    "usage_alert": (
        "Hello {name},\n"
        "\n"
        "Your usage of {metric_name} has reached {value} {unit}, which is "
        "at or above the alert threshold of {threshold} {unit} you set. "
        "The threshold was crossed at {at} by event {event_id}.\n"
        "\n"
        "This is an informational message; no action is required.\n"
        "\n"
        "{signature}\n"),
}


@dataclass(frozen=True)
class Notification:
    to: str
    subject: str
    body: str

    def render(self):
        """The whole message as RFC-822-ish text: headers, blank line, body."""
        return f"To: {self.to}\nSubject: {self.subject}\n\n{self.body}"


def wrap_paragraphs(text, width=WIDTH):
    """Wrap every paragraph of ``text`` to ``width`` columns.

    Paragraphs are separated by blank lines.  Lines that start with a space
    (pre-formatted tables) and lines that already fit are left alone.
    """
    out = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        if any(ln.startswith(" ") for ln in lines) or all(len(ln) <= width for ln in lines) and len(lines) > 1:
            out.append(block)
            continue
        flat = " ".join(ln.strip() for ln in lines)
        out.append(textwrap.fill(flat, width=width, break_long_words=False, break_on_hyphens=False))
    return "\n\n".join(out)


def _fill(template, **values):
    values.setdefault("signature", SIGNATURE)
    return wrap_paragraphs(TEMPLATES[template].format_map(values))


def invoice_summary_table(inv):
    """Right-aligned money table: subtotal, discount, tax, total, credit, due."""
    rows = [("Subtotal", inv.subtotal)]
    if inv.discount_total:
        rows.append(("Discounts", -inv.discount_total))
    rows.append((inv.tax.rule.label, inv.tax.tax))
    rows.append(("Total", inv.total))
    if inv.credit_total:
        rows.append(("Prepaid credit", -inv.credit_total))
    rows.append(("Amount due", inv.amount_due))
    texts = [format_money(m) for _, m in rows]
    w = max(len(t) for t in texts)
    return "\n".join(f"  {label:<24}{text:>{w}}" for (label, _), text in zip(rows, texts))


def invoice_issued(inv):
    c = inv.customer
    notes = "".join(f"Note: {n}\n\n" for n in inv.notes)
    body = _fill(
        "invoice_issued", name=c.name, number=inv.number, period=inv.period.label(),
        due_amount=format_money(inv.amount_due), due_date=inv.due.isoformat(),
        summary=invoice_summary_table(inv), notes=notes)
    return Notification(c.email, f"Invoice {inv.number} from Kettle Cloud: {format_money(inv.amount_due)} due {inv.due.isoformat()}", body)


def _reached(state, action):
    for step, when in state.reached:
        if step.action == action:
            return step, when
    return None


def payment_reminder(state, customer):
    """Reminder for the latest reminder step reached; ValueError when none was."""
    rec = state.receivable
    count = state.reminders
    if not count:
        raise ValueError(f"{rec.invoice} has not reached a reminder step")
    reminder_line = "This is the first reminder." if count == 1 else f"This is reminder number {count}."
    fee = _reached(state, "late_fee")
    suspend = _reached(state, "suspend")
    next_step = ""
    if state.fee:
        next_step = f"A late fee of {format_money(state.fee)} will be added to your next invoice.\n\n"
    elif fee is None and suspend is None:
        next_step = "Please arrange payment to avoid late fees.\n\n"
    amount = format_money(rec.amount)
    body = _fill("payment_reminder", name=customer.name, invoice=rec.invoice, amount=amount,
                 due_date=rec.due.isoformat(), reminder_line=reminder_line, next_step=next_step)
    return Notification(customer.email, f"Reminder: invoice {rec.invoice} ({amount}) is overdue", body)


def suspension_notice(state, customer):
    """Notice that the account was suspended; ValueError when the state was not."""
    hit = _reached(state, "suspend")
    if hit is None:
        raise ValueError(f"{state.receivable.invoice} has not reached the suspend step")
    rec = state.receivable
    fee_line = (f"A late fee of {format_money(state.fee)} applies to your next invoice."
                if state.fee else "")
    amount = format_money(rec.amount)
    body = _fill("suspension_notice", name=customer.name, invoice=rec.invoice, amount=amount,
                 due_date=rec.due.isoformat(), customer_id=customer.id,
                 suspended_on=hit[1].isoformat(), fee_line=fee_line)
    return Notification(customer.email, f"Account {customer.id} suspended: invoice {rec.invoice} unpaid", body)


def usage_alert(fired, customer, metrics):
    """Alert notice; ``metrics`` is the catalogue's MetricSet (names, units, precision)."""
    metric = metrics.get(fired.alert.metric)
    body = _fill("usage_alert", name=customer.name, metric_name=metric.name,
                 value=format_qty(fired.value, metric.precision), unit=metric.unit,
                 threshold=format_qty(fired.alert.threshold, metric.precision),
                 at=format_instant(fired.at), event_id=fired.event_id)
    return Notification(customer.email, f"Usage alert: {metric.name} reached {format_qty(fired.value, metric.precision)} {metric.unit}", body)


def notifications_for_run(run):
    """Every invoice and dunning notice of a BillingRun, in customer/invoice order."""
    out = []
    for inv in sorted(run.invoices, key=lambda i: i.number):
        if inv.customer.email:
            out.append(invoice_issued(inv))
    book = run.dataset.customers
    for st in sorted(run.dunning, key=lambda s: s.receivable.invoice):
        cust = book.get(st.receivable.customer)
        if not cust.email:
            continue
        if st.reminders:
            out.append(payment_reminder(st, cust))
        if st.suspended:
            out.append(suspension_notice(st, cust))
    return out
