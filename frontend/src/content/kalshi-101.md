# Kalshi 101 (for dummies)

Kalshi is a **prediction market**: a regulated exchange where you trade on whether real-world events will happen. Instead of stocks, you buy **event contracts** — bets with exactly two outcomes.

## The one idea that explains everything

Every Kalshi market is a question with a YES or NO answer, decided by a rule:

> *"Will the average US gas price be above $3.880 on Jul 13?"*

Each contract is worth **exactly $1 if you're right and $0 if you're wrong**. That's it. Everything else — prices, odds, spreads — is just people negotiating over how likely YES is.

## Prices are probabilities

A YES contract trading at **38¢** means the market collectively thinks there's roughly a **38% chance** the event happens.

- Buy YES at 38¢ → if the event happens you get $1.00 back (win 62¢); if not, you lose your 38¢.
- Buy NO at 69¢ → you profit when the event *doesn't* happen.

!!! tip "The mental flip"
    Cheap contracts = unlikely events with big payouts. Expensive contracts = likely events with small payouts. A 3¢ YES pays ~33x when it hits — because it usually doesn't.

Note YES price + NO price is always slightly *more* than $1 when you're buying — that gap is the spread plus fees (below).

## Where the money comes from (and goes)

Kalshi is an exchange, not a casino. You're not betting against "the house" — you're trading against **other people**. For every YES buyer there's a NO buyer on the other side, and the exchange holds the combined $1 until the event resolves. The house takes a **fee**, win or lose; it doesn't care who wins.

This matters: in a casino the odds are built against you. On an exchange, your real opponent is *the other traders' judgment*. If they're sloppy and you're careful, you can genuinely have an edge. (That's the entire thesis of this dashboard.)

## The order book: bid, ask, spread

- **Ask** — the cheapest price someone will sell you a contract at (you buy here).
- **Bid** — the highest price someone will pay you for one (you sell here).
- **Spread** — the gap between them. Tight spread = active market. Wide spread = you pay a tax to enter and exit.

You can place **limit orders** (name your price, wait) instead of taking the ask. On thin markets this matters a lot.

## Fees

Kalshi charges a trading fee when your order fills, roughly:

```
fee = 0.07 × contracts × price × (1 − price)
```

rounded up to the next cent. Two consequences:

- Fees are biggest for 50¢ (coin-flip) contracts (~1.75¢/contract) and tiny at the extremes.
- **Fees kill "sure thing" trades.** A 99¢ contract that pays $1 earns you 1¢ gross — and the fee is 1¢. You risked 99¢ for nothing.

There is **no fee at settlement** — losers pay nothing extra, winners collect the full $1.

## Settlement: read the rules, always

Every market resolves according to its **rules page** — an exact source, an exact time, an exact number. Not the vibe of the question, the *text* of the rule.

!!! warning "The fine print is the market"
    "Gas prices this week" actually means "the AAA national average as published on a specific morning." "Rotten Tomatoes score above 70" means the displayed score at exactly 10:00 AM ET on a specific day. People lose money betting on what they *think* the question means. Read the rules tab before every trade.

## Buying, selling, and getting out early

You don't have to hold to settlement. If your 33¢ YES is now worth 38¢, you can sell and pocket the difference (minus a second fee). If news breaks against you, you can sell to salvage what's left. Selling before settlement = second fee; holding to settlement = no extra fee.

## What Kalshi is (legally)

Kalshi is a **CFTC-regulated exchange** (the same regulator as commodity futures). It's legal in the US, holds customer funds in segregated accounts, and reports to a federal regulator. That's the main difference from offshore betting sites. It is still real money and real risk — regulation doesn't make losing impossible; it makes the plumbing trustworthy.

## Quick-start checklist

1. Find a market. Read the **rules tab**, not just the title.
2. Ask: *what would I need to know to price this better than strangers?* If nothing — skip.
3. Check the source the market settles on (AAA, NWS, Rotten Tomatoes…). It's usually public.
4. Compare your honest probability to the ask price. Trade only when there's a real gap — after fees.
5. Size small. See [Bankroll & risk](#/wiki/bankroll).
