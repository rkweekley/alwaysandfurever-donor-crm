# Reports

The intent behind each required report. SQL implementations land in `reports/`
during Phase 1. All amounts are integer cents in storage; divide by 100 for display.

## Donation reports
- **Total by date range** — `SUM(amount_cents)` where `donation_date` between A and B.
- **Total by month/year** — group by `strftime('%Y-%m', donation_date)`.
- **Gross vs net after fees** — `SUM(amount_cents)`, `SUM(fee_cents)`, `SUM(net_cents)`.
- **By source** — join `sources`, group by source (Stripe, PayPal, Zeffy, Facebook, …).
- **By campaign** — join `campaigns`, group by campaign.
- **By fund / designation** — join `funds`, group by fund.
- **Recurring donor revenue** — filter `is_recurring=1`.
- **New vs returning donors** — first gift in range vs prior giving history.

## Donor reports
- **Top donors** — order donors by `donation_total_cents` desc.
- **First-time donors** — `first_gift_date` within range.
- **Lapsed donors** — `last_gift_date` older than N months, total > 0.
- **Monthly donors** — `is_recurring_donor=1`.
- **Donors without mailing addresses** — `address_line1 IS NULL`.
- **Donors over a threshold** — `donation_total_cents >= X` (or largest gift >= X).
- **Donors needing thank-you calls** — recent gift + open follow-up note, or no
  acknowledgment yet.
- **Donors who gave through multiple platforms** — `COUNT(DISTINCT source_id) > 1`.

## Receipt / acknowledgment reports
- **Donations needing receipts** — `receipt_status='unsent'`.
- **Donations needing thank-you notes** — `thank_you_status='pending'`.
- **Annual giving summaries** — per donor, per calendar year (for tax letters).
- **In-kind donation receipts** — `is_in_kind=1`, grouped by donor/year.
- **Check / cash donation logs** — `source` in (check, cash), by date range.

## Export
Every report should export to **CSV/XLSX** for board reports, mailing houses, and
the accountant.
