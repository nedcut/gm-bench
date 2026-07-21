import type { Leaderboard as LeaderboardData } from "../types";
import Ladder from "./Ladder";

export default function Hero({ data }: { data: LeaderboardData }) {
  const fingerprint = data.contract?.contract_fingerprint;
  const cap = data.publication.frozen_output_token_cap;
  const registryFrozen = data.publication.model_registry_frozen === true;
  const modelCount = data.models.length;

  return (
    <section className="hero" id="top">
      <div className="shell hero-top">
        <p className="hero-brand">
          GM-Bench<span>.</span>
        </p>
        {/* LEARNING TODO: rewrite this h1 in your own wire voice (5–10 words).
            Keep the finding; drop any leftover marketing tone. */}
        <h1>Phase one: 0 of {modelCount} models beat the scripted bar</h1>
        <p className="hero-sub">
          Agents run a franchise in a seeded hockey-style league — contracts, trades, drafts, cap
          pressure — across multi-season episodes. Eight scripted heuristics set the bar; a
          hidden-information oracle sets the ceiling.
        </p>
        <div className="hero-actions">
          <a className="btn-primary" href="#leaderboard">
            Open standings
          </a>
        </div>
        <p className="hero-facts">
          {fingerprint && (
            <>
              contract <b>{fingerprint}</b> ·{" "}
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
      <div className="shell" style={{ paddingBottom: 0 }}>
        <Ladder data={data} />
      </div>
    </section>
  );
}
