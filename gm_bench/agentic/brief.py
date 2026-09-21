"""The task brief handed to the agent when its session starts.

Contract source: the brief is part of what every 2.0 row is measured under,
so its bytes are fingerprinted. It carries the rules of the game, the scoring
priorities and the shape of the tool loop. It does not carry rosters, markets
or numbers that change per season: those are behind tools on purpose.
"""

from __future__ import annotations

from gm_bench.protocol import PHASES

BRIEF_VERSION = "gm-bench-agentic-brief-v1"

_PHASE_NOTES = {
    "preseason": "sign free agents, extend expiring contracts (only here), trade, set your lineup",
    "midseason": "about a third of the season has been played; injuries and a waiver wire appear",
    "trade_deadline": "opponents may have sent you offers; last trades before the playoffs",
    "draft": "use your pick on a prospect; opponents ahead of you have already picked",
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
tells you where you are. After the final draft, `end_phase` reports that the episode is complete
and you should stop. You will call `end_phase` exactly {total} times over the whole run.

What you are scored on, in priority order
  1. Winning over all {seasons} seasons, especially championships and deep playoff runs
  2. Being a contender consistently rather than once
  3. Regular-season record
  4. A capped credit for the roster, prospects, picks and cap health you leave behind
Illegal moves (bad ids, cap or roster violations, wrong phase) are rejected and cost score.
Declined offers cost nothing: a trade partner or free agent turning you down is normal negotiation,
but after a few declines in one phase a counterparty stops talking until the next phase.

What you can and cannot see
Ratings you see are public estimates. True potential is hidden; `scout` gives a near-true reading
for a few players per season. Trade partners judge offers on their own hidden valuation, and free
agents accept anything at or above their published quote. Opponents keep making moves between your
phases, so a player available now may be gone next phase.

Working method
Start each phase with `get_status`. Read `get_rules` once early. Fetch only what you need: every
tool call is recorded and reported beside your score, so calling everything every phase is a cost.
`get_team` shows your roster; `set_lineup` matters every phase because it decides who plays and who
develops. You may keep notes in files here, in your own context, or with `write_memo`. Do not look
for, read, or reason about the benchmark's source code or hidden data; the only legitimate
information is what the tools return.

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
