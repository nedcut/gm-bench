# Frontier models versus long-horizon asset management

> Draft. Publication is blocked until the fixed-cap API panel contains at least
> eight strictly eligible registered models. No v1 score below is a current
> ranking.

GM-Bench asks an agent to run the same procedurally generated hockey franchise
for five seasons: manage cap, negotiate trades, scout and draft prospects, and
trade current wins against future asset value. The benchmark is reproducible
in ways many model evaluations are not: its simulator and scoring contract are
fingerprinted, public and held-out seed panels are committed independently,
scripted policies provide absolute reference points, and raw run evidence is
hash-linked from compact published artifacts.

The withdrawn v1 runs exposed two reasons to distrust an easy headline. First,
the documented prospect-scout action did not match the simulator, harming
models unevenly while leaving scripts untouched. Second, observed output ranged
from roughly 263 to 2,993 tokens per decision. The same nominal model scored
very differently through an API and a coding harness. That table mixed model
quality, output budget, and harness behavior, so it is evidence motivating the
new protocol—not a ranking.

The `sota-v2` publication answers those failures directly. It fixes scouting,
separates API and coding-harness lanes, reports input and output tokens rather
than hiding output inside a total dominated by prompts, permits exactly one
measured JSON repair, and reports accepted and rejected actions by strategic
mechanic. The headline lane uses the same 1,024-token safety ceiling with
reasoning disabled for every model. Before any full result, all registered
models must pass a smoke audit; a call reaching 768 output tokens or showing
cap-induced truncation raises the whole lane to 2,048. The smoke audit selects
that single cap—1,024 by default, or 2,048 if the trigger fires—and the chosen
cap is then frozen for the entire published lane, so every headline number
shares one response budget rather than mixing 1,024- and 2,048-token results.
Actual token, cost, and latency efficiency are reported beside score rather than
folded into it.

The scale will show four anchors: the hidden-information Oracle diagnostic,
the strongest honest scripted policy (`pick-trader`), the best eligible API
model, and `random`. This makes both model progress and remaining benchmark
headroom visible. The central question is not “can an LLM emit plausible GM
prose?” It is which model-plus-standardized-scaffold systems can beat a few
hundred lines of transparent heuristic at compounding, long-horizon asset
allocation under one fixed response budget.

## Results

Generated from `web/src/data/leaderboard.json` after the lane freeze. Do not
hand-copy provisional numbers here.
