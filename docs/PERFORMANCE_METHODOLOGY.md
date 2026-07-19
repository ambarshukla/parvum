# Performance methodology: three answers to "how did this account do?"

`gold_performance` and `gold_performance_summary` (added alongside this doc)
compute the same client's since-inception return three different ways. They
disagree on purpose. This doc explains why, using the actual figures the
pipeline produces.

## The question underneath the question

A portfolio's value changed over a period. How much of that change is the
manager's doing, and how much is just the client's own money moving in and
out? Every performance methodology is a different answer to that split.

- **Time-weighted return (TWR)** removes the client's cash flows from the
  calculation entirely. Chop time at every flow, compute the pure market
  return of each sub-period, chain-link the sub-periods together. The
  investor's contribution or withdrawal timing has *zero* effect on the
  number. This is the fair way to judge a manager, who doesn't control when
  clients deposit or withdraw.
- **Modified Dietz** is the pre-computer approximation of the same idea: one
  formula over the whole period, with each flow weighted by the fraction of
  the period it was actually invested (a flow on day one counts fully; a flow
  on the last day counts for nothing). It doesn't need daily valuations the
  way true TWR does — historically the point of it — and it tracks TWR
  closely whenever flows are small relative to the portfolio.
- **Internal rate of return (IRR / money-weighted return)** keeps the flow
  timing *in*, deliberately. It answers "what rate of return did the
  investor's actual dollars actually earn," and a badly-timed deposit (right
  before a drawdown) genuinely hurts this number even though the manager did
  nothing differently. This is the investor's lived experience, not the
  manager's report card.

If a period has no flows, all three collapse to the same number. They only
diverge when money moves mid-period — which is why `gold_performance`'s test
data deliberately puts flows in the *middle* of each month (see D-040) rather
than at the boundaries.

## The pipeline's actual figures

Computed from the corrected wealth series (D-040's cash-continuity fix and
D-041's holdings-dedupe fix both applied), for the ~three-month window
2026-04-20 → 2026-07-17:

| Client   | Wealth begin  | Wealth end    | Net flow  | TWR      | Dietz    | IRR (annualized) |
|----------|--------------:|--------------:|----------:|---------:|---------:|------------------:|
| Hartwell | $42,936,410.86 | $41,143,303.15 | +$137,500 | −4.49%  | −4.49%  | −17.34% |
| Okafor   | $3,141,777.11  | $2,938,462.42  | +$100,000 | −11.24% | −11.23% | −38.98% |
| Reyes    | $1,897,109.81  | $1,712,828.75  | +$25,000  | −10.77% | −10.79% | −37.71% |

Two things stand out, and both are the point of building three methods
instead of one:

**TWR and Dietz agree to within a few basis points, for every client.**
That's expected — these clients' flows are small relative to portfolio size
(Hartwell's net flow is 0.3% of its ending wealth), which is exactly the
regime where Modified Dietz's linear day-weighting approximates true
chain-linked TWR well. If a future scenario put a much larger flow in,
expect the gap to widen — that gap *is* Dietz's approximation error, and
watching it grow with flow size is the methodology lesson made visible.

**IRR is far more negative than either return-based figure, and that's not
a bug in any of the three.** It's the annualization convention. TWR and
Dietz above are reported as *period* returns — the actual, un-annualized
change over the ~89-day window, matching GIPS practice for sub-annual
periods. IRR is reported *annualized*, because "internal rate of return"
conventionally always means a per-annum rate. A −4.49% quarter, extrapolated
naively to a year, reads like a much worse number even though nothing about
the underlying market move changed. Comparing an annualized figure against
two non-annualized ones side by side — rather than picking one convention
and hiding the other — is deliberate: it's the annualization-convention
difference a report has to be able to explain, not paper over.

## How each is actually computed

**TWR** (`gold_performance.daily_twr_return`, `twr_index_since_inception`):
for each business day, `daily_return = (wealth_today − external_flow_today)
/ wealth_yesterday − 1`. The flow is entirely excluded from the numerator so
it contributes nothing to the return, only to the portfolio's size for the
*next* day's baseline. Daily returns chain-link into a growth-of-$1 index
via `EXP(SUM(LN(1 + r)))` — a log-sum, computed exactly by SQL window
functions with no UDF required, and the standard trick used by real
performance systems for the same reason: geometric chaining as repeated
multiplication is numerically worse-conditioned over long series than a
sum-then-exponentiate.

**Modified Dietz** (`gold_performance_summary.dietz_since_inception`):
`(wealth_end − wealth_begin − net_flow) / (wealth_begin + Σ flow_i × w_i)`,
where `w_i = (period_days − days_since_period_start_i) / period_days`. A
flow on the inception day itself is treated as already inside
`wealth_begin` (see below) rather than double-counted as a separate flow.

**IRR** (`gold_performance_summary.irr_since_inception_annualized`): solved
by bisection on the NPV-at-rate-r function over the client's actual cash
flow dates — `wealth_begin` as an outflow at inception, each subsequent flow
as its own signed cash flow, `wealth_end` as an inflow at the final date.
Bisection rather than Newton's method: this runs once per gold rebuild for a
handful of clients, so there's no performance reason to risk Newton's
occasional divergence on a badly-shaped NPV curve. No external solver
library — root-finding by bisection is a few lines of Python, and the
dependency isn't worth adding for something this small.

## The inception-day boundary rule

Every method above needs one convention decision that's easy to get subtly
wrong: what happens to the flow on the very first day of the measured
period? `gold_performance`'s daily TWR chain starts at index 1 (the second
row), leaving `daily_twr_return` `NULL` on the client's first date — there's
no prior day to compare against, so no return can be attributed to that day
at all. Its flow is simply *inside* `wealth_begin_usd`, the same way a real
statement's opening balance already reflects whatever settled before the
statement period began. Modified Dietz's flow sum and IRR's cash-flow list
both follow the identical rule (`WHERE as_of > inception_date`), so a flow
that happened to land on inception day is never counted twice — once inside
`wealth_begin` and again as a separate flow — across any of the three
methods.

## Why this data needed two upstream fixes first

Both `gold_performance` and this doc's example figures came *after*
discovering and fixing two data-integrity bugs in the same session, in the
order the actual work happened:

1. **D-040**: the cash-generator fixture had no day-over-day continuity — a
   flow recorded in the statements never actually landed in the next day's
   opening balance. Computing TWR against that data would have shown a
   phantom, constant daily bleed purely from the inconsistency, unrelated to
   any real return.
2. **D-041**: `silver_positions`'s holdings dedupe let a `MISTYPED_ISIN`
   defect double-count a position's market value (the corrupted copy and its
   correct sibling in the other format no longer shared a dedupe key, so
   both survived). This showed up as single-day wealth spikes that fully
   reverted the next day — exactly the kind of artifact that makes a demo
   fall apart the moment someone asks "why did it jump 12% and then drop
   right back?"

Both were found by the same discipline: probe the actual data before
building the analytics that assume it's clean. A performance engine is only
as trustworthy as the wealth series underneath it — this doc's whole premise
(showing genuine, small, explainable disagreements between three
methodologies) would have been undermined by either bug's noise.
