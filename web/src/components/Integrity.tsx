import type { Leaderboard as LeaderboardData } from "../types";

export default function Integrity({ data }: { data: LeaderboardData }) {
  const contract = data.contract;
  const cap = data.publication.frozen_output_token_cap;
  const registryFrozen = data.publication.model_registry_frozen === true;
  return (
    <section className="section section-alt" id="integrity">
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Integrity</p>
          <h2>The measurement is pre-registered.</h2>
          <p>
            The score-affecting contract and statistical plan are frozen and fingerprinted before
            official results. Route selection remains visibly pending until every registered smoke
            clears the gate below.
          </p>
        </div>
        <div className="fact-grid">
          <div className="fact">
            <h4>Frozen contract</h4>
            <p>
              Simulator, scoring, presets, and action schemas hash to{" "}
              <code>{contract?.contract_fingerprint ?? "—"}</code>. Any change to a score-affecting
              source changes the fingerprint and invalidates comparability.
            </p>
          </div>
          <div className="fact">
            <h4>Fixed compute policy</h4>
            {cap ? (
              <p>
                One common {cap.toLocaleString("en-US")}-token output ceiling, reasoning off, JSON
                mode on; exact provider routes are {registryFrozen ? "pinned" : "pending smoke verification"}.
                The v1 table ranked output budgets, not models; v2 holds compute constant.
              </p>
            ) : (
              <p>The common compute policy is still pending and no fixed-ceiling claim is published.</p>
            )}
          </div>
          <div className="fact">
            <h4>Tiers, not ranks</h4>
            <p>
              The statistical plan froze before any data: Holm-corrected paired contrasts, per-model
              p-values reported as descriptive only, and models with overlapping uncertainty
              published as one tier.
            </p>
          </div>
          <div className="fact">
            <h4>Evidence or nothing</h4>
            <p>
              Paid runs are serial, checkpointed, and spend-capped; raw artifacts are hash-linked;
              valid poor results are never re-run. When v1 failed this standard, it was withdrawn —
              not patched.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
