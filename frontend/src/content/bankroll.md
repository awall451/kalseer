# Bankroll & risk

How not to blow up. Sizing discipline is worth more than picking skill — a good picker with bad sizing goes broke; a mediocre picker with good sizing survives to improve.

## The only three rules that matter

1. **Decide your bankroll first** — the number you could lose entirely and shrug. It's entertainment budget, not rent.
2. **Bet fractions, never chunks.** A single position should be a small slice of the bankroll (this system caps at 10%).
3. **Expect losing streaks.** A 55% edge still loses 4+ in a row regularly. If a normal streak would knock you out, your bets are too big.

## Kelly sizing (the math of "how much")

The Kelly criterion computes the bankroll fraction that maximizes long-run growth:

```
fraction = (fair − price) / (1 − price)
```

Example: fair 55%, price 33¢ → (0.55 − 0.33) / 0.67 ≈ **33%** of bankroll.

!!! warning "Never bet full Kelly"
    Full Kelly assumes your probability estimate is *exactly right*. It never is. Everyone serious bets a fraction — this system uses **quarter Kelly** (≈8% in the example above). Half your edge estimate is wrong? Quarter Kelly keeps you alive to find out.

## Variance: what winning actually feels like

A +EV bet at 38¢ with 55% real odds loses **45 times out of 100**. Positive expected value doesn't feel like winning — it feels like *slightly more than half* your reasonable bets working out while people around you hit parlays. The profit shows up in the long-run average, not the highlight reel.

!!! note "The $10 test"
    Before any trade, say the loss out loud: *"~40% chance I just lose all $4."* If the sentence feels fine, trade. If you catch yourself thinking "but it probably won't happen" — stop. That's the gambler talking, not the analyst.

## Correlation: the silent account-killer

Five "different" bets that all need gas prices to rise are **one bet** in five costumes. When the number dips, they die together. Real diversification = different *underlying events* (weather + movies + econ data), not different strikes of the same thing.

## This system's hard caps

The paper-trading pipeline enforces these in code — the bot literally can't override them on a bad reasoning day:

- Max **3 new positions** per day
- Max **10% of equity** in any single position
- Max **40% of equity** at risk across all open positions

Steal them for your real account. They're boring. Boring survives.
