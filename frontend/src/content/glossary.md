# Glossary

Quick definitions, alphabetical-ish, grouped by theme.

## Market mechanics

- **Event contract** — a bet with two outcomes that pays $1 (right) or $0 (wrong).
- **YES / NO** — the two sides of every contract. Buying NO = betting the event won't happen.
- **Ask** — the price you can buy at right now. **Bid** — the price you can sell at right now.
- **Spread** — ask minus bid. The cost of impatience.
- **Limit order** — an order at a price you name, which waits for a counterparty. **Market/taker order** — takes the current ask/bid immediately (pays the fee).
- **Maker / taker** — the resting order that provided liquidity vs. the order that took it. Kalshi's fee hits takers.
- **Order book** — the stack of resting bids and asks at each price.
- **Strike** — the threshold number in a market family ("above 3.880", "above 3.900" are strikes of the same event).
- **Settlement / resolution** — the market being decided against its rules source.
- **Close time** — when trading stops (often before resolution).
- **Open interest** — contracts currently held. **Volume** — contracts traded.
- **Liquidity** — how much you can trade without moving the price.

## Betting math

- **Implied probability** — the price read as odds: 38¢ = 38%.
- **Fair value** — *your* researched estimate of the true probability.
- **Edge** — fair value minus price (for a buy). The thing that must exceed fees.
- **EV (expected value)** — average outcome if the bet repeated forever: `p×win − (1−p)×loss`. Positive EV still loses often; it wins *on average*.
- **Variance** — how far results swing around the average. High-variance +EV bets (3¢ lottery tickets) lose most of the time by design.
- **Kelly criterion** — formula for bet sizing that maximizes long-term growth; always used fractionally. See [Bankroll & risk](#/wiki/bankroll).
- **Bankroll** — money you can lose entirely without consequence. The unit all sizing is measured in.
- **Longshot bias** — the human tendency to overpay for unlikely-but-exciting outcomes.
- **Ladder** — same-direction bets across multiple strikes. **Spread** — opposite bets on two strikes, profiting in between. See [Strategies](#/wiki/strategies).
- **Hedge** — a bet that wins in the world where your other bet loses. (A ladder is not one.)

## Measurement (how this system grades itself)

- **Calibration** — whether your stated probabilities match reality: of all your "70%" calls, ~70% should happen. The dashboard's calibration chart plots exactly this.
- **Brier score** — mean squared error of probability estimates. 0 = oracle, 0.25 = coin-flip guessing. Lower is better.
- **ROI (return on investment)** — net profit ÷ total staked, after fees.
- **Paper trading** — trading with pretend money to measure skill before risking real money. Phase 1 of this whole project.
- **Mark to market** — valuing open positions at current prices instead of entry price.
- **Slippage** — the gap between the price you expected and the price you actually got.
