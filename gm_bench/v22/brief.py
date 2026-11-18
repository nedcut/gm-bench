"""The 2.2 task brief (draft).

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``). Forked
from ``gm_bench/agentic/brief.py``, a frozen 2.0 source. The brief carries
the rules of the game, the scoring priorities and the shape of the tool
loop. It states mechanics and never gives strategy advice. It does not carry
rosters, markets or numbers that change per season: those are behind tools.

What changed from the 2.0 brief, each from a misreading the 2.1 panels
showed (``docs/bench_v2_2_spec.md``, phase 2): when the season is played,
when the end-of-run credit is counted and which part of it is capped, that a
lineup persists, the exact decline limit, that schema failures are free, and
that tool calls are reported and not scored.
"""

from __future__ import annotations

from gm_bench.protocol import PHASES

BRIEF_VERSION = "gm-bench-agentic-brief-v2"

_PHASE_NOTES = {
    "preseason": "sign free agents, extend expiring contracts (only here), trade, set your lineup",
    "midseason": "about a third of the season has been played; injuries and a waiver wire appear",
    "trade_deadline": "opponents may have sent you offers, which are withdrawn when this phase closes",
    "draft": "use your pick on a prospect; trades, signings and `set_lineup` stay open",
}


def task_brief(seasons: int, team_name: str, team_id: int) -> str:
    phases = "\n".join(f"  {index + 1}. {phase}: {_PHASE_NOTES[phase]}" for index, phase in enumerate(PHASES))
    total = seasons * len(PHASES)
    return f"""You are the general manager of {team_name} (team id {team_id}) in a 12-team hockey league.
You run the franchise for {seasons} seasons through the `gm-bench` tools. This is a benchmark: your
score is computed when the last season ends and nothing you do outside the tools counts.

How the calendar works
Each season has four decision phases, in this order:
{phases}
In every phase you may call tools as many times as you like: read the state, gather information,
make moves, then call `end_phase`. That is the only way time advances. Moves apply immediately and
cannot be undone. Once you call `end_phase`, opponents act and the next phase opens; the response
tells you where you are. Games are played at two points, each with the roster and lineup you have at
that moment: the first third of the regular season when the preseason closes, and the other two
thirds plus the playoffs when the draft phase closes. After the final draft, `end_phase` reports
that the episode is complete and you should stop. You will call `end_phase` exactly {total} times
over the whole run.

What you are scored on, in priority order
  1. Winning over all {seasons} seasons, especially championships and deep playoff runs
  2. Being a contender consistently rather than once
  3. Regular-season record
  4. A credit for the roster, prospects, picks and cap room you leave behind. It is counted after
     the final season's contracts have expired, so a player whose contract ends with the final
     season is not part of it. Picks for the draft after the final season count. The cap-room
     part is capped, and roster depth stops counting at 24 players; the rest is not capped.
Illegal moves (bad ids, cap or roster violations, wrong phase, breaking a trade rule) are rejected
and cost score. A call whose arguments do not fit the tool's schema is rejected before it reaches
the game and costs nothing. Declined offers cost nothing: a trade partner or free agent turning you
down is normal negotiation, but after 2 declines in one phase a counterparty refuses further offers
until the next phase.

What you can and cannot see
Ratings you see are public estimates. True potential is hidden; `scout` gives a near-true reading
for a few players per season. Trade partners judge offers on their own hidden valuation, and free
agents accept anything at or above their published quote. Opponents keep making moves between your
phases, so a player available now may be gone next phase.

Working method
Start each phase with `get_status`. Read `get_rules` once early. Tool calls are recorded and
reported beside your score; they do not change the score. `get_team` shows your roster; `set_lineup`
decides who plays and who develops. A lineup you set stays in force until you set another, and a
player you add later dresses only when a slot in it is empty. You may keep notes in files here, in
your own context, or with `write_memo`. Do not look for, read, or reason about the benchmark's
source code or hidden data; the only legitimate information is what the tools return.

Begin now with `get_status`."""


def nudge_message(season: int, phase: str, seasons: int, nudge_number: int, max_nudges: int) -> str:
    """What the driver sends when the harness stopped before the episode ended.

    Sent into the same session, so the agent keeps its context. Counted and
    reported per episode; after ``max_nudges`` the rest of the episode is
    scored as failed decisions.
    """
    return (
        f"You stopped before the episode was complete. You are in season {season} of {seasons}, "
        f"phase {phase}, and this phase is still open. Continue from here: call `get_status`, "
        f"finish this phase, and keep calling `end_phase` until it reports that the episode is "
        f"complete. Only tool calls advance the game; a text reply ends your turn. "
        f"(Reminder {nudge_number} of {max_nudges}.)"
    )


def server_instructions() -> str:
    """The short hint the MCP server returns at initialize time."""
    return (
        "GM-Bench: manage a hockey franchise through these tools for several seasons. "
        "Call get_status first in every phase and end_phase to advance. The task brief in your "
        "first message has the full rules."
    )
