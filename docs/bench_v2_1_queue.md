# Deferred changes for the next 2.0-lane contract version

GM-Bench 2.0 is frozen at agentic fingerprint `07de948a4f4afbae`
(`docs/bench_v2_spec.md`). Everything below was found after the freeze. Each
item either changes a fingerprinted file (`gm_bench/agentic/tools.py`,
`brief.py`, `episode.py`, `mcp_server.py`), so fixing it is a new benchmark
version, changes a post-hoc rule that a published row relied on, or is a
driver change that can alter future measurements without a version bump
(disclosed per the spec's freeze rules). None of them is fixed in 2.0. The spec reserves 2.1 for simulator mechanics; these
items ride on whichever contract version comes next.

Recorded 2026-09-28 from the pre-release audit. Line references are to
`main` at `c19a1b7`.

## Contract behaviour that differs from 1.0 without a reason

These also appear in the spec under "How 2.0 differs from 1.0 beyond the
interface", because they affect any 1.0-versus-2.0 comparison.

1. **Penalty parity for malformed calls.** A tool call that fails the input
   schema is rejected before the simulator and not penalized
   (`episode.py` `_execute`, `tools.py` `validate_arguments`). The same
   mistake in 1.0 is a protocol violation. Decide whether schema failures on
   move tools should count as illegal actions, as in 1.0, or stay free, and
   make the schema and the simulator agree on ranges (`years` has
   `minimum: 1` and no maximum in the schema; the simulator allows 1 to 5).
2. **Draft class visibility and scouting.** `list_draft_class` answers only
   in the draft phase, while 1.0 shows a draft class summary in every phase.
   `scout` accepts a prospect id in any phase, so the only way to scout
   prospects before the draft is to guess their ids, which the audit then
   reports as `guessed_read`. Either list the class (or its summary) in
   every phase, or restrict prospect scouting to the draft phase.
3. **`inspect_player` promises prospects.** Its description says "any team,
   free agent, or prospect", but `League._inspect_player` looks the id up in
   signed players only and answers "unknown player id" for a prospect. Fix
   the lookup or the description.

## Engine and server defects

4. **Non-object arguments are logged as `{}`.** `episode.py` `_log_call`
   (about line 289) writes `arguments` as `{}` when the call's arguments were
   not an object. Live, such a call fails with "arguments must be an
   object"; on replay it runs with `{}`, which is valid for tools with no
   required arguments (`end_phase`, the read tools). Replay can then diverge
   from the live episode. Log the raw value, or log the call as not executed.
5. **A call queued on the dispatch lock can run after `stop()`.**
   `SocketMcpServer.stop()` sets `_stop`, hangs up on every connection and
   joins their threads, but a request already read and waiting on
   `dispatch_lock` in `_LockedMcpServer._dispatch` still executes when it
   gets the lock. Check `_stop` inside the lock and refuse the call.
6. **Accept-loop admission.** A deferred review nit on the atomicity of
   connection admission against `stop()` in `SocketMcpServer._accept_loop`.
   The current code registers a connection under `_live_lock` and re-checks
   `_stop` there; review it again together with item 5.
7. **Guard notice rounding.** The phase-guard notice formats the guard with
   `:.0f`, so a sub-second guard (tests only) prints as `0s`. Cosmetic, but
   the text is a contract source.
8. **The stdio entry point resets the guard clock.** `AgenticEpisode.from_ledger`
   restores recorded phase durations but starts the open phase's guard
   clock from the reload, so a restarted stdio server gives the open phase a
   fresh guard period. The socket path the driver uses keeps one engine for
   the whole episode and is not affected.

## Driver behaviour to settle before the next panel

These are driver files, so they can change without a version bump, but a
change alters what a new row measures against the existing ones.

9. **Retry time off the phase clock only for OpenCode.** The driver takes a
   provider stall's backoff off the guard clock when the harness exits on a
   retryable error, and OpenCode's silent in-process 429 retries are caught
   by the silent-harness stop. Claude Code's in-process `api_retry` waits and
   Codex's stream reconnects happen inside a running invocation, so they
   count against the phase guard. No panel phase came near the guard, but
   the treatment is unequal across harnesses.

## Audit and publication

10. **Id-based audit failures can be sidestepped.** A successful read on a
    guessed id (`scout`, `inspect_player`, `inspect_team`) marks the id as
    seen, so an agent with leaked ids could read each one before moving on
    it and pass as clean. The audit also cannot catch a leak of values
    rather than ids (for example true potential). Consider a
    publication-time check that ranks the players an agent drafted or
    signed by true potential against the public prediction: an agent that
    systematically beats the public estimate without scouting is using
    hidden information.
11. **Rows do not record which audit rules admitted them.** `audit.py` is
    post-hoc and not fingerprinted, and the guessed-draft-pick exception
    (#163) was added after a panel had run. Record an audit version or
    digest in each row (or fingerprint `audit.py`), so a row says which
    rules it passed.
12. **What the harness sends the model is not fingerprinted.** The
    fingerprint covers the tool surface and brief the server offers, not
    the harness's own system prompt, tool list or deferral (Claude Code
    shows MCP tools by name and loads schemas through ToolSearch). The
    prompt check proposed in #166 (open at the time of writing) records what
    each harness sends; decide whether a row should carry it.
