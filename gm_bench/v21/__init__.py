"""GM-Bench 2.1: the 2.0 agentic lane with the records fix and score-v2.

Nothing here edits a 1.0 or 2.0 contract source, so both of those
fingerprints and every published row stay as they are. 2.1 is built on top:

- ``rules``     ``League21``: records reset each season, and the bracket's
                exact playoff odds are recorded for scoring.
- ``scoring``   ``score-v2``: expected playoff value and every season's own
                wins, end-state terms unchanged.
- ``runner``    plays a scripted policy under 2.1 (references and canaries).
- ``episode``   ``AgenticEpisode21``: the frozen 2.0 engine on ``League21``,
                scored with score-v2. Same tools, same brief.
- ``contract``  the 2.1 contract block and fingerprint over these files.

Background and evidence: ``docs/score_v2_proposal.md``,
``docs/score_deep_dive.md`` and ``docs/bench_v2_1_queue.md`` items 15-16.
"""
