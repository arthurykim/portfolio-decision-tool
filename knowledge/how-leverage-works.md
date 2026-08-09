# How leverage and exposure work

Leverage means controlling more of something than you paid for, using borrowed
money. If you put up $1,000 and borrow $1,000, you control $2,000 of stock. That
$2,000 is your **exposure**; the $1,000 you actually own is your **equity**. The
ratio between them — here 2x — is your leverage.

Leverage does not change what an investment does. It changes how much of the
outcome lands on you, in both directions, and it introduces a way to lose that
does not exist without it: being forced out before you are proven right.

## The multiplication is symmetric, the survival is not

At 2x leverage, a 10% gain in the asset becomes a 20% gain on your money, and a
10% loss becomes a 20% loss. That part is symmetric and unsurprising.

What is not symmetric is what a loss does to your ability to continue. Losses
compound against you: after a 50% loss you need a 100% gain to get back to even.
Leverage moves you into that punishing zone faster.

| leverage | asset falls 10% | asset falls 25% | asset falls 33% | asset falls 50% |
|---|---|---|---|---|
| 1x (no borrowing) | −10% | −25% | −33% | −50% |
| 2x | −20% | −50% | −67% | **wiped out** |
| 3x | −30% | −75% | **wiped out** | wiped out |
| 5x | −50% | **wiped out** | wiped out | wiped out |

Read the bottom row carefully. At 5x, a 20% decline — something the S&P 500 has
done repeatedly, and the kind of drop an unleveraged investor waits out — takes
every dollar you have. The asset does not need to go to zero. It only needs to
fall by 1/leverage.

## The margin call is the part that hurts

Your broker lends you the money and holds your position as collateral. They
require your equity to stay above a **maintenance margin**, often around 25–30%
of the position. When a falling price pushes you below it, you get a **margin
call**: add cash immediately, or the broker sells your position for you.

This is what makes leverage genuinely dangerous rather than merely volatile.
Being liquidated converts a temporary paper loss into a permanent realised one.
An unleveraged investor who holds through a 35% crash gets their money back when
the market recovers. A leveraged investor who was liquidated at the bottom does
not participate in the recovery at all — they are already out, with the loss
locked in.

The forced selling also arrives at the worst possible time, because margin calls
cluster exactly when prices are falling hardest and cash is most scarce.

## A worked example

You have $10,000 and borrow another $10,000 to buy $20,000 of an index fund at
2x. Maintenance margin is 30%.

- The index falls 15%. The position is worth $17,000. You still owe $10,000, so
  your equity is $7,000 — you have lost 30% of your money on a 15% move.
- Equity is now $7,000 / $17,000 = 41% of the position. Still above 30%.
- The index falls 15% more (about 28% from the start — an ordinary bear market).
  The position is worth $14,450, the debt is still $10,000, and your equity is
  $4,450, or 31%. You are one bad day from a margin call.
- One more 5% drop triggers it. The broker sells. You keep roughly $3,700 of
  your original $10,000, and you own nothing when the recovery comes.

The unleveraged version of this investor is down 33% on paper, owns every share
they started with, and recovers fully when the index does.

## Borrowing costs run whether you are right or not

Margin loans charge interest — often several percent a year, and it is charged
daily on the borrowed balance. That is a headwind your position must overcome
before you make anything. Held for years, the interest alone can consume the
advantage that leverage was supposed to provide.

## Leveraged ETFs decay in choppy markets

Funds labelled 2x or 3x reset their leverage **daily**. Over a single day they
do what they say. Over longer periods they do something else, because the daily
reset means the return depends on the *path* prices took, not just the start and
end points.

Take an index at 100 that falls 10% to 90, then rises 11.1% back to 100 — flat
over two days. A 3x fund falls 30% to 70, then rises 33.3% to 93.3. The index is
unchanged; the leveraged fund lost 6.7%.

This is called **volatility decay**, and it is a structural feature of the
product, not a fee or a mistake. It means leveraged ETFs can lose money over a
period in which the underlying index went nowhere, and it gets worse the choppier
the market is. They are built as short-term trading instruments, and their own
prospectuses generally say so.

## Other forms of the same thing

Leverage appears under many names: margin loans, futures, options, contracts for
difference, and the "5x / 10x / 50x" offered by crypto exchanges. Buying a home
with a 20% down payment is 5x leverage too — the differences are that a mortgage
is not marked to market daily and cannot margin-call you for a price decline, so
the forced-sale risk is far lower.

## Why it stays popular

Leverage is attractive because the arithmetic of gains is real. Doubled exposure
in a rising market doubles returns, and in a long bull market leveraged
strategies look brilliant right up until the first sharp drawdown.

The honest summary is that leverage raises expected loss in the scenarios that
end your participation, while raising returns in scenarios you would have
survived anyway. It converts volatility — which a long-term holder can simply
outlast — into a permanent risk of ruin. That is the trade, and it is why this
tool models unleveraged portfolios only.

*This is educational material, not investment advice. Margin trading can lose
more than the amount you deposit.*
