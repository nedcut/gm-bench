import type { Leaderboard as LeaderboardData } from "../types";
import Ladder from "./Ladder";

export default function Hero({ data }: { data: LeaderboardData }) {
  const fingerprint = data.contract?.contract_fingerprint;
  const cap = data.publication.frozen_output_token_cap;
  return (
    <section className="hero" id="top">
      <div className="shell">
        <p className="hero-eyebrow">A pre-registered front-office benchmark for LLM agents</p>
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
          <a className="btn-ghost" href="#protocol">
            Read the protocol
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
              · <b>{cap.toLocaleString("en-US")}-token</b> output ceiling · reasoning off · pinned routes
            </>
          )}
        </p>
      </div>
      <div className="shell">
        <Ladder data={data} />
      </div>
    </section>
  );
}
