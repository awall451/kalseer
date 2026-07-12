# Taxes

What we actually know about Kalshi and US taxes, as of mid-2026.

!!! danger "Not tax advice"
    This page is orientation, not advice. The tax treatment of prediction-market
    contracts is **genuinely unsettled** — the IRS has issued no formal guidance
    specific to CFTC-regulated event contracts. For anything beyond pocket
    change, talk to a CPA. Laws also change; verify anything here before filing.

## The one rule with no asterisk

**All winnings are taxable income whether or not you receive a tax form.** No 1099 ≠ no taxes. The IRS requires you to report income regardless of whether anyone told them about it.

## What paperwork Kalshi sends

Per Kalshi's help center and CPA write-ups (2026):

- **1099-B** — may be issued for trading proceeds above reporting thresholds (~$600+ gross). Coverage is inconsistent; many traders get nothing.
- **1099-MISC** — referral bonuses and promo rewards, not trading profits.
- **1099-INT** — the interest Kalshi pays on cash balances (that "3.25% interest" on the buy panel). This one is plain old interest income.

Whatever arrives (or doesn't), **your own records are the real books** — see below.

## The unsettled part: what *kind* of income?

Nobody authoritative has ruled. The candidate treatments, and why it matters:

| Treatment | Consequence |
|---|---|
| **Capital gains/losses** | Losses offset gains, plus up to $3,000/yr against ordinary income. Short-term rates for quick trades. |
| **Section 1256 contracts** | The regulated-futures regime: 60/40 long/short-term split, mark-to-market at year end. Argued by some CPAs since Kalshi is CFTC-regulated; unconfirmed by the IRS. |
| **Gambling income** | Winnings are ordinary income; losses deductible only against winnings — and under the 2025 tax law changes, only **90%** of losses are deductible. Worst case for an active trader. |
| **Other/ordinary income** | The catch-all fallback. |

!!! warning "Plan for the least favorable"
    Until the IRS speaks, the safe posture: keep records that support *any* of these treatments, and don't spend your winnings' tax share. If profits stay small (tens of dollars), this is a non-issue in practice — but the reporting obligation technically exists at any size.

## Records to keep (this is 90% of the work)

For every trade, keep: date, market, side, contracts, entry price, fees paid, exit/settlement result, profit or loss. Plus deposits and withdrawals.

!!! tip "This dashboard already does it"
    Every position in this system is logged with entry price, fees, settlement result, and P&L — and the daily git commits are timestamped history. When real money starts, the same ledger becomes your tax record. Export at year end, done.

## Practical notes

- **Fees reduce your gains** — track them; they're part of your cost basis under any treatment.
- **Interest on idle cash** (the 1099-INT part) is taxable every year regardless of trading.
- **State taxes** exist too and follow their own rules.
- **Losing year?** You still may want the records — loss deductibility depends on the treatment above.
- Deposits and withdrawals are **not** taxable events; profits are.
