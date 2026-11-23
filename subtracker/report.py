"""Turn the subscriptions found into a terminal table, an HTML page and a CSV."""

from __future__ import annotations

import csv
import html
from datetime import date
from pathlib import Path

from .detect import CardFees, Loan, Possible, Subscription


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _d(d: date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def totals(subs: list[Subscription]) -> tuple[float, float]:
    active = [s for s in subs if s.active]
    return sum(s.monthly_cost for s in active), sum(s.yearly_cost for s in active)


def text_report(subs: list[Subscription], possible: list[Possible], problems: list[str],
                fees: list[CardFees] | None = None, overlaps: list[str] | None = None,
                loans: list[Loan] | None = None, moves: list[str] | None = None) -> str:
    lines = []
    for p in problems:
        lines.append(f"! {p}")
    bills = [s for s in subs if s.is_bill and s.active]
    subs = [s for s in subs if not s.is_bill]
    active = [s for s in subs if s.active]
    stopped = [s for s in subs if not s.active]
    row = "{:<28} {:>10}  {:<36} {:<36} {:<14}"
    if active:
        lines.append("ACTIVE SUBSCRIPTIONS")
        lines.append(row.format("Name", "Amount", "Billed", "Card", "Next renewal"))
        for s in active:
            lines.append(row.format(s.name[:28], _money(s.amount), s.frequency, s.card[:36], _d(s.next_renewal)))
        monthly, yearly = totals(subs)
        lines.append(f"\nTotal: {_money(monthly)} a month, {_money(yearly)} a year\n")
    else:
        lines.append("No active subscriptions found.\n")
    if stopped:
        lines.append("STOPPED OR EXPIRED (no recent charge)")
        lines.append(row.format("Name", "Amount", "Billed", "Card", "Last charged"))
        for s in stopped:
            lines.append(row.format(s.name[:28], _money(s.amount), s.frequency, s.card[:36], _d(s.last_charged)))
        lines.append("")
    if moves:
        lines.append("MOVED TO ANOTHER CARD")
        lines.extend(f"  - {n}" for n in moves)
        lines.append("")
    if overlaps:
        lines.append("POSSIBLE OVERLAPS")
        lines.extend(f"  - {n}" for n in overlaps)
        lines.append("")
    if possible:
        lines.append("CHECK THESE (known services with no clear billing pattern yet)")
        for p in possible:
            times = f", {p.times} charges, latest" if p.times > 1 else ""
            lines.append(f"  {p.name} {_money(p.amount)} on {p.card}{times}, {_d(p.charged)} "
                         + ("(charged at uneven times)" if p.times >= 3
                            else f"(yearly renewal was due {_d(p.renews_if_yearly)}, no charge seen)" if p.overdue
                            else f"(if yearly, renews around {_d(p.renews_if_yearly)})"))
        lines.append("")
    if bills:
        lines.append("BILLS AND UTILITIES (amounts vary; not counted in the totals above)")
        lines.append(row.format("Name", "Average", "Billed", "Card", "Next bill"))
        for s in bills:
            lines.append(row.format(s.name[:28], _money(s.average), s.frequency, s.card[:36], _d(s.next_renewal)))
        monthly, yearly = totals(bills)
        lines.append(f"\nBills total: about {_money(monthly)} a month, {_money(yearly)} a year\n")
    if loans:
        lines.append("LOANS (not counted in the totals above)")
        for l in loans:
            pay = (f"{_money(l.payment)} a month, last paid {_d(l.last_paid)}, next around {_d(l.next_payment)}"
                   if l.payment else "no payments in these files")
            lines.append(f"  {l.card}: {pay}; interest about {_money(l.interest_per_month)} a month")
        lines.append("")
    if fees:
        lines.append("INTEREST AND FEES (not counted in the totals above)")
        for f in fees:
            lines.append(f"  {f.card}: {_money(f.last_12_months)} in the last 12 months, "
                         f"about {_money(f.per_month)} a month")
            if f.annual_fee:
                lines.append(f"    includes a {_money(f.annual_fee)} annual card fee, "
                             f"next due around {_d(f.annual_fee_next)}")
    return "\n".join(lines)


def write_csv(subs: list[Subscription], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Type", "Status", "Amount", "Billed", "Card", "First charged",
                    "Last charged", "Next renewal", "Per month", "Per year"])
        for s in subs:
            w.writerow([
                s.name, "Bill" if s.is_bill else "Subscription", "Active" if s.active else "Stopped", f"{s.typical:.2f}", s.frequency,
                s.card, s.first_charged.isoformat(), s.last_charged.isoformat(),
                s.next_renewal.isoformat() if s.active else "",
                f"{s.monthly_cost:.2f}", f"{s.yearly_cost:.2f}",
            ])


def html_report(subs, possible, problems, today: date, fees: list[CardFees] | None = None,
                overlaps: list[str] | None = None, loans: list[Loan] | None = None,
                moves: list[str] | None = None) -> str:
    e = html.escape
    bills = [s for s in subs if s.is_bill and s.active]
    subs = [s for s in subs if not s.is_bill]
    active = [s for s in subs if s.active]
    stopped = [s for s in subs if not s.active]
    monthly, yearly = totals(subs)
    bill_monthly, _ = totals(bills)

    def history(s: Subscription) -> str:
        items = "".join(f"<li>{_d(t.date)} · {_money(t.amount)}</li>" for t in reversed(s.charges))
        return f"<details><summary>{len(s.charges)} charges</summary><ul>{items}</ul></details>"

    def due_class(s: Subscription) -> str:
        return " soon" if (s.next_renewal - today).days <= 7 else ""

    active_rows = "".join(
        f"<tr><td class='name'>{e(s.name)}"
        + (" <span class='tag'>price changed</span>" if s.price_changed else "")
        + f"</td><td class='num'>{_money(s.amount)}</td><td>{e(s.frequency)}</td>"
        f"<td>{e(s.card)}</td><td class='date{due_class(s)}'>{_d(s.next_renewal)}</td>"
        f"<td class='num'>{_money(s.monthly_cost)}</td><td>{history(s)}</td></tr>"
        for s in active
    )
    stopped_rows = "".join(
        f"<tr><td class='name'>{e(s.name)}</td><td class='num'>{_money(s.amount)}</td>"
        f"<td>{e(s.frequency)}</td><td>{e(s.card)}</td><td class='date'>{_d(s.last_charged)}</td>"
        f"<td>{history(s)}</td></tr>"
        for s in stopped
    )
    possible_rows = "".join(
        f"<tr><td class='name'>{e(p.name)}</td><td class='num'>{_money(p.amount)}</td>"
        f"<td>{e(p.card)}</td><td class='date'>{_d(p.charged)}</td>"
        + (f"<td>Uneven timing ({p.times} charges)</td></tr>" if p.times >= 3
           else f"<td class='date soon'>Was due {_d(p.renews_if_yearly)}, no charge seen</td></tr>" if p.overdue
           else f"<td class='date'>{_d(p.renews_if_yearly)}</td></tr>")
        for p in possible
    )
    bill_rows = "".join(
        f"<tr><td class='name'>{e(s.name)}</td><td class='num'>{_money(s.average)}</td>"
        f"<td>{e(s.frequency)}</td><td>{e(s.card)}</td><td class='date{due_class(s)}'>{_d(s.next_renewal)}</td>"
        f"<td class='num'>{_money(s.monthly_cost)}</td><td>{history(s)}</td></tr>"
        for s in bills
    )
    fee_rows = "".join(
        f"<tr><td class='name'>{e(f.card)}"
        + (f"<br><span class='note'>Annual fee {_money(f.annual_fee)}, next around {_d(f.annual_fee_next)}</span>"
           if f.annual_fee else "")
        + f"</td><td class='num'>{_money(f.last_12_months)}</td>"
        f"<td class='num'>{_money(f.per_month)}</td><td><details><summary>{len(f.charges)} charges</summary><ul>"
        + "".join(f"<li>{_d(t.date)} · {e(t.description)} · {_money(t.amount)}</li>" for t in reversed(f.charges))
        + "</ul></details></td></tr>"
        for f in (fees or [])
    )
    loan_rows = "".join(
        f"<tr><td class='name'>{e(l.card)}</td>"
        f"<td class='num'>{_money(l.payment) if l.payment else '–'}</td>"
        f"<td class='date'>{_d(l.next_payment) if l.next_payment else '–'}</td>"
        f"<td class='num'>{_money(l.interest_per_month)}</td>"
        f"<td><details><summary>{len(l.charges)} entries</summary><ul>"
        + "".join(f"<li>{_d(t.date)} · {e(t.description)} · {_money(t.amount)}</li>" for t in reversed(l.charges))
        + "</ul></details></td></tr>"
        for l in (loans or [])
    )
    overlap_html = (
        "<h2>Possible overlaps</h2><p class='note'>Worth checking whether you need all of these.</p><ul class='overlaps'>"
        + "".join(f"<li>{e(n)}</li>" for n in overlaps) + "</ul>"
    ) if overlaps else ""
    moves_html = (
        "<h2>Moved to another card</h2><p class='note'>Same service, now paid from a different card.</p>"
        "<ul class='overlaps'>" + "".join(f"<li>{e(n)}</li>" for n in moves) + "</ul>"
    ) if moves else ""
    problem_html = "".join(f"<p class='problem'>{e(p)}</p>" for p in problems)

    def section(title, note, head, rows):
        if not rows:
            return ""
        ths = "".join(f"<th>{h}</th>" for h in head)
        return (f"<h2>{title}</h2><p class='note'>{note}</p>"
                f"<div class='scroll'><table><thead><tr>{ths}</tr></thead><tbody>{rows}</tbody></table></div>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>My Subscriptions</title>
<style>
:root {{ --bg:#f7f7f5; --card:#fff; --text:#1d1d1f; --muted:#6b6b70; --line:#e4e4e0; --accent:#2f6f4f; --warn:#a4520f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161617; --card:#1f1f21; --text:#ececec; --muted:#9a9aa0; --line:#333336; --accent:#6fcf97; --warn:#f2a65a; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:26px; }} h2 {{ margin:36px 0 4px; font-size:18px; }}
.note, .sub {{ color:var(--muted); margin:0 0 12px; }}
.totals {{ display:flex; gap:12px; flex-wrap:wrap; margin:20px 0 8px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 18px; min-width:160px; }}
.tile b {{ display:block; font-size:24px; font-variant-numeric:tabular-nums; }}
.tile span {{ color:var(--muted); font-size:13px; }}
.scroll {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; white-space:nowrap; }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; }}
tr:last-child td {{ border-bottom:0; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.name {{ font-weight:600; white-space:normal; min-width:170px; }}
.soon {{ color:var(--warn); font-weight:600; }}
.tag {{ font-size:11px; font-weight:500; color:var(--warn); border:1px solid currentColor; border-radius:4px; padding:0 4px; margin-left:4px; }}
details summary {{ cursor:pointer; color:var(--accent); }} details ul {{ margin:6px 0 0; padding-left:18px; color:var(--muted); }}
.overlaps {{ background:var(--card); border:1px solid var(--line); border-radius:10px; margin:0; padding:12px 12px 12px 32px; }}
.overlaps li {{ margin:4px 0; }}
.problem {{ background:var(--card); border-left:3px solid var(--warn); padding:8px 12px; }}
</style></head>
<body><main>
<h1>My Subscriptions</h1>
<p class="sub">From your credit card files, updated {_d(today)}. Renewals due within a week are highlighted.</p>
{problem_html}
<div class="totals">
  <div class="tile"><b>{_money(monthly)}</b><span>per month</span></div>
  <div class="tile"><b>{_money(yearly)}</b><span>per year</span></div>
  <div class="tile"><b>{len(active)}</b><span>active subscriptions</span></div>
</div>
{section("Active", "Charged on schedule. Totals include only these.",
         ["Name", "Amount", "Billed", "Card", "Next renewal", "Per month", "History"], active_rows)
 or "<p>No active subscriptions found yet. Add CSV files to the data folder and run it again.</p>"}
{overlap_html}
{moves_html}
{section("Stopped or expired", "These used to charge regularly but the latest charge didn't come.",
         ["Name", "Amount", "Billed", "Card", "Last charged", "History"], stopped_rows)}
{section("Check these", "Well-known services charged once, or at uneven times, so the billing cycle isn't clear yet.",
         ["Name", "Amount", "Card", "Last charged", "If yearly, renews"], possible_rows)}
{section(f"Bills and utilities · about {_money(bill_monthly)} a month",
         "Regular household bills. The amount changes each time, so this shows the recent average. Not counted in the subscription totals.",
         ["Name", "Average", "Billed", "Card", "Next bill (estimate)", "Per month", "History"], bill_rows)}
{section("Loans", "Monthly loan payments and the interest in them. Not counted in the subscription totals.",
         ["Loan", "Monthly payment", "Next payment (estimate)", "Interest per month", "History"], loan_rows)}
{section("Interest and fees", "Charged by the card itself. Not counted in the subscription totals.",
         ["Card", "Last 12 months", "Per month", "Charges"], fee_rows)}
</main></body></html>
"""
