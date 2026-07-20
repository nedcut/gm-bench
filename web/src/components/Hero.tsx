import type { Leaderboard as LeaderboardData } from "../types";
import Ladder from "./Ladder";

export default function Hero({ data }: { data: LeaderboardData }) {
  const fingerprint = data.contract?.contract_fingerprint;
  const cap = data.publication.frozen_output_token_cap;
  const registryFrozen = data.publication.model_registry_frozen === true;
  return (
    <section className="hero" id="top">
      <div className="shell">
        <p className="hero-eyebrow">
          <span>A pre-registered front-office benchmark for LLM agents</span>
          <a href="https://github.com/nedcut">By Ned Cutler</a>
        </p>
        <a className="hero-result" href="#leaderboard">
          <span>Phase-one result</span>
          <strong>{data.models.length} models tested. 0 beat the scripted bar.</strong>
          <i aria-hidden="true">View evidence →</i>
        </a>
        <h1>
          Can a language model out-manage a <span className="bar-word">scripted front office</span>?
        </h1>
        <p className="hero-sub">
          GM-Bench puts agents in charge of a franchise in a fictional hockey-style league —
          contracts, trades, drafts, cap pressure — for seeded, replayable multi-season episodes.
          Eight scripted heuristics set the bar and a hidden-information oracle sets the ceiling.{" "}
          <strong>The board opens only when the pre-registered evidence is complete.</strong>
        </p>
        <div className="hero-actions">
          <a className="btn-primary" href="#leaderboard">
            See the board
          </a>
          <a
            className="btn-ghost"
            href="https://github.com/nedcut/gm-bench/blob/main/docs/blog/sota-v2-findings.md"
          >
            Read the findings
          </a>
          <a className="btn-text" href="https://github.com/nedcut/gm-bench/releases/tag/sota-v2-phase-one-2026-07-19">
            Open the evidence release
          </a>
        </div>
        <p className="hero-facts">
          {fingerprint && (
            <>
              frozen contract <b>{fingerprint}</b> ·{" "}
            </>
          )}
          <b>{data.preset.seeds.length} seeds</b> × <b>{data.preset.seasons} seasons</b> × 3 repeats
          {cap && (
            <>
              {" "}
              · <b>{cap.toLocaleString("en-US")}-token</b> output ceiling · reasoning off
            </>
          )}
          {registryFrozen ? " · routes pinned" : " · routes pending smoke verification"}
        </p>
      </div>
      <div className="shell">
        <Ladder data={data} />
      </div>
    </section>
  );
}
