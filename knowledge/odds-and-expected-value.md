# How odds, moneyline, and expected value work

Betting odds are a way of writing down a price on an uncertain outcome. Learning
to read them is useful well beyond betting, because the same arithmetic —
implied probability, expected value, and the house's cut — is what separates a
positive-expectancy activity from a negative one.

## Moneyline: the American format

A moneyline quote is a number with a sign, based on $100.

- **Negative (favourite).** −150 means you must risk $150 to win $100. A $50 bet
  wins $33.33, returning $83.33 total.
- **Positive (underdog).** +200 means a $100 risk wins $200. A $50 bet wins $100,
  returning $150 total.

A bigger negative number means a stronger favourite; a bigger positive number
means a longer shot. −110 on both sides is the standard "even" market, and the
fact that it is −110 rather than +100 is where the sportsbook makes its money.

## The other formats say the same thing

- **Decimal** (common outside the US): total return per $1 staked. 2.50 means a
  $10 bet returns $25 — your $10 back plus $15 profit.
- **Fractional** (traditional UK): profit per stake. 3/2 means $2 risked wins $3.

Conversions: +200 = 3.00 decimal = 2/1. −150 = 1.667 decimal = 2/3.

## Odds are a probability in disguise

Every price implies a probability of winning that would make the bet break even.

- Negative moneyline: `implied % = odds / (odds + 100)`, using the absolute
  value. −150 → 150/250 = **60%**.
- Positive moneyline: `implied % = 100 / (odds + 100)`. +200 → 100/300 = **33.3%**.
- Decimal: `implied % = 1 / decimal odds`. 2.50 → **40%**.

This is the useful skill. A price is a claim about how likely something is, and
you can only judge a bet by comparing that implied probability against your own
honest estimate.

## The vig: why the percentages add up to more than 100

Take a game priced −110 on both sides. Each side implies 110/210 = 52.4%.
Together that is **104.8%**, not 100%. The extra 4.8 percentage points is the
**vigorish** — the house's built-in margin, also called the overround or juice.

That surplus is the entire business model. The book does not need to predict
winners; it needs balanced action, after which it keeps the difference no matter
who wins.

## Expected value

Expected value (EV) is the average result per bet if you could repeat it forever:

```
EV = (probability of winning × amount won) − (probability of losing × amount risked)
```

Risk $110 to win $100 at a true 50/50:

```
EV = (0.50 × $100) − (0.50 × $110) = $50 − $55 = −$5
```

You lose $5 per $110 risked on average — about −4.5%. Not because you picked
badly, but because the price was worse than the true odds. Repeated often
enough, that arithmetic dominates everything else.

A bet is only positive-EV if your estimated probability beats the implied
probability by more than the vig. At −110 you need to be right about **52.4%** of
the time just to break even, and above that to profit.

## Why "due for a win" is false

Independent events have no memory. A fair coin that landed heads eight times has
a 50% chance of heads on the ninth. Believing otherwise is the **gambler's
fallacy**, and strategies built on it — most famously doubling your bet after
each loss — do not change EV. They just reshape the distribution into many small
wins and rare catastrophic losses, and they run into table limits and finite
bankrolls exactly when they matter.

## How this compares to investing

The structural difference is the sign of the expected value.

| | casino / sportsbook | broad market investing |
|---|---|---|
| Expected value | negative by design | historically positive |
| Source of return | other players, minus the house cut | company earnings and economic growth |
| Effect of more time | losses converge toward the house edge | returns have historically compounded |
| Can everyone win? | no — it is zero-sum minus the vig | yes — the pie can grow |

Time is the clearest divide. In a negative-EV game, playing more moves you
*closer* to losing your expected share — the edge grinds you down with certainty.
In a positive-EV holding, more time has historically worked in your favour.

This is also the honest frame for short-term trading. It sits between the two:
no fixed house edge, so a real edge is possible, but costs and spreads act like a
small vig on every round trip. See the trading article.

## Reading a price critically

The habit worth taking away: convert any quoted odds into an implied probability,
then ask whether you genuinely believe the true probability is better than that.
If you cannot say why your estimate should beat the market's, the price is the
best available estimate, and the vig means you are paying to disagree with it.

*Educational material about how odds are quoted and priced. Nothing here is
betting advice or a suggestion to gamble. Gambling carries real risk of loss and
can be addictive; in the US, help is available at 1-800-GAMBLER.*
