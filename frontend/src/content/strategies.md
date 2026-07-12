# Strategies

Ways to structure trades — from the boring-but-solid to the fun-but-spicy. Every one of them lives or dies on the same rule: **your estimated probability has to beat the price by more than the fees.**

## Value betting (the foundation)

Estimate the real probability yourself, from primary sources. Compare to the market price. Trade only the gap.

!!! example "The gas trade (real example from this system)"
    Market: *"AAA average above $3.880 on Jul 13"* asking 33¢ (33%).
    Research: AAA's own site — the literal settlement source — already showed **$3.882**, above the line, with a +7¢/week trend.
    Our fair estimate: ~55%. Edge: 22¢ per contract before fees. That gap is the whole trade.

The skill isn't predicting the future — it's noticing when the market's price disagrees with **checkable public data**.

## The ladder

Buy the same direction at multiple strikes with different prices. Cheap insurance + lottery upside in one structure.

!!! example "The $4 gas ladder"
    - $2 on YES **>3.880** @ 38¢ (likely, small payout)
    - $2 on YES **>3.900** @ 3¢ (unlikely, pays ~$62)

    | Outcome | Net |
    |---|---|
    | Gas ≤ $3.880 | **−$4** (both lose) |
    | $3.881–3.900 | **≈ +$1** (safe leg covers the punt) |
    | > $3.900 | **≈ +$63** (both hit) |

!!! danger "A ladder is NOT a hedge"
    Both legs bet the same direction. There is a world — the number dips — where **every rung loses at once**. A ladder shapes your payout; it does not guarantee one. If someone says "guaranteed," they're selling something.

## The spread (betting on "in between")

Buy YES on a low strike and NO on a higher strike of the same event. Now you profit when the number lands **between** them, lose on either side. This *is* a defined-risk structure — but it still loses when the number escapes the band. Useful when you think a market overrates a big move.

## Near-arbitrage at the extremes

Sometimes a market prices a near-certainty at 97–98¢ when the real probability is ~99.5% (e.g., "high temp below 91°" while it's raining at 4pm with an observed max of 78°F). Buying the last few cents is nearly free money — **but check the fee first**. At 99¢ the 1¢ fee eats 100% of the profit.

!!! tip "The fee gate"
    Rule of thumb from this system: mid-priced trades need **~10¢+ of edge** to be worth it; extreme-priced trades need the gross profit to be at least **double the fee**.

## Longshot bias (sell the lottery tickets)

Humans systematically overpay for exciting 3–7¢ YES contracts (someone always thinks the crazy thing will happen). Selling that excitement — buying NO at 93–97¢ — is a small, steady, boring edge across many markets. The catch: one hit wipes out many wins, so size small and diversify across uncorrelated events.

## Threshold arithmetic

When a market resolves on a number crossing a line, do the actual math on how far the number is from the line and how fast it moves.

!!! example "Rotten Tomatoes knife-edge"
    Score sits at exactly **71** with 133 reviews; market asks "above 70?" and prices YES at 72%. Arithmetic: just **2 rotten reviews** with no fresh ones drops the display to 70. That's not 72% safe — that's a coin flip wearing confidence. We bought NO.

## Resolution-rule reading

The most reliable edge on Kalshi requires no prediction at all: **read the rules more carefully than the crowd.** Which station reports the temperature? Which timestamp does the score freeze at? Casual money bets the headline; careful money bets the fine print.

## What doesn't work

- **Betting the news.** By the time you read it, the price moved. (Crude oil headlines → gas *pump* prices take 1–2 weeks to follow; know your lag.)
- **Chasing losses.** The market doesn't know you're down.
- **Forcing action.** No-trade days are profitable days you didn't lose. This system's guardrails hard-cap trades per day for exactly this reason.
