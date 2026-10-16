import { REPO_BLOB } from "../site";
import { findings, type Findings, type ModelFindings, type Term } from "../findings";
import { HARNESSES, num, signed, vendorOf } from "../v2";

const pct = (share: number) => `${num(share * 100, 0)}%`;
const list = (items: string[]) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);
const range = (values: number[]) => {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return lo.toFixed(1) === hi.toFixed(1) ? num(lo) : `${num(lo)}–${num(hi)}`;
};

function GapChart({ total, terms }: { total: Term; terms: Term[] }) {
  const rows = [total, ...terms];
  const lo = Math.min(0, ...rows.map((row) => row.ci95[0]));
  const hi = Math.max(0, ...rows.map((row) => row.ci95[1]));
  const x = (value: number) => ((value - lo) / (hi - lo)) * 100;
  return (
    <div className="gap-chart">
      {rows.map((row) => (
        <div
          key={row.key}
          className={`gap-row${row.key === "final_score" ? " is-total" : ""}`}
          title={`${row.label}: ${signed(row.mean)} (95% interval ${signed(row.ci95[0])} to ${signed(row.ci95[1])})`}
        >
          <span className="gap-label">
            {row.label}
            <small>{row.detail}</small>
          </span>
          <span className="gap-track" aria-hidden="true">
            <span className="gap-zero" style={{ left: `${x(0)}%` }} />
            <i style={{ left: `${Math.min(x(0), x(row.mean))}%`, width: `${Math.abs(x(row.mean) - x(0))}%` }} />
            <s style={{ left: `${x(row.ci95[0])}%`, width: `${x(row.ci95[1]) - x(row.ci95[0])}%` }} />
          </span>
          <span className="gap-value">
            {signed(row.mean)}
            <small>{row.key === "final_score" ? `${signed(row.ci95[0])} to ${signed(row.ci95[1])}` : `${pct(row.share)} of gap`}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

export default function FindingsPage({ data = findings }: { data?: Findings }) {
  const gap = data.family_gap;
  const by = new Map(data.models.map((m) => [m.model, m]));
  const openai = gap.openai.map((name) => by.get(name)!);
  const claude = gap.claude.map((name) => by.get(name)!);
  const term = (key: string) => gap.terms.find((t) => t.key === key)!;
  const total: Term = {
    key: "final_score",
    label: "Final score",
    detail: "the terms below sum to it",
    mean: gap.final_score.mean,
    ci95: gap.final_score.ci95,
    share: 1,
  };
  const opus = by.get("claude-opus-5-5");
  const [corrLo, corrHi] = gap.extra_empty_vs_gap_correlation;
  const harnessesOf = (rows: ModelFindings[]) => list([...new Set(rows.map((m) => HARNESSES[m.harness] ?? m.harness))]);
  return (
    <article className="page findings">
      <h1>Findings</h1>
      <p className="lede">
        On the 2.1 panel the OpenAI rows ({list(gap.openai)}) lead {list(gap.claude)} by{" "}
        <b>{num(gap.final_score.mean)} points</b> of final score, paired seed by seed, and are ahead on{" "}
        {gap.final_score.ahead} of {gap.seeds} seeds. Most of that gap is the roster left at the end: the Claude 5.5
        models let contracts lapse in season 5. Winning is the next part. Empty phases explain little of it.
      </p>

      <h2>Where the gap comes from</h2>
      <p>
        Per seed, the mean of the OpenAI rows minus the mean of the Claude rows, split by score-v2 term. Line: 95%
        interval.
      </p>
      <GapChart total={total} terms={gap.terms} />
      <ul>
        <li>
          The end-of-run roster terms are {signed(term("end_roster").mean)} of the {num(gap.final_score.mean)}. The
          Claude rows are scored on {range(claude.map((m) => m.roster_at_end))} players under contract, against{" "}
          {range(openai.map((m) => m.roster_at_end))} for the OpenAI rows.{" "}
          {list(claude.map((m) => String(m.episodes_ending_with_5_or_fewer)))} of their {claude[0].episodes} games end
          with 5 or fewer players.
        </li>
        <li>
          In the season-5 preseason the Claude rows make {range(claude.map((m) => m.season_5_extensions_per_episode))}{" "}
          extensions per game, against {range(openai.map((m) => m.season_5_extensions_per_episode))} for the OpenAI rows.
        </li>
        <li>
          Winning adds {signed(term("winning").mean)}. Cap room gives back {num(-term("cap_room").mean)}: the Claude rows
          end with more unused room.
        </li>
      </ul>

      <h2>What the empty-phase count measures</h2>
      <p>
        An empty phase is one the model closed after at most reading the status: no other query and no move. On the
        standings it reads as "did nothing". Mostly it is not:
      </p>
      <ul>
        <li>
          The Codex rows read the status in every phase, so a phase with nothing to do is not empty for them. Opus and
          Sonnet end {list(claude.map((m) => pct(m.rate_ended_without_status_read)))} of their phases without reading it.
        </li>
        {opus && (
          <li>
            {opus.empty_drafts_with_no_pick} of Opus's {opus.empty_phases} empty phases are drafts in which it held no
            pick to use.
          </li>
        )}
        <li>
          Missed decisions are rare: across the {data.models.length} rows, {data.drafts_closed_holding_unused_pick} of{" "}
          {data.drafts} drafts closed with a pick unused.
        </li>
        <li>
          Paired by seed, a Claude model's extra empty phases do not track its deficit (correlation {signed(corrLo, 2)}{" "}
          to {signed(corrHi, 2)} across the OpenAI-Claude pairs).
        </li>
      </ul>

      <div className="table-scroll">
        <table className="data-table findings-table">
          <thead>
            <tr>
              <th>Model</th>
              <th className="r">Empty phases</th>
              <th className="r">of which no-pick drafts</th>
              <th className="r">Phases with no status read</th>
              <th className="r">Drafts closed with an unused pick</th>
              <th className="r">Roster at end</th>
              <th className="r">Season-5 extensions / game</th>
              <th className="r">Games ending below the season-4 score</th>
            </tr>
          </thead>
          <tbody>
            {data.models.map((m) => (
              <tr key={m.model}>
                <th scope="row">
                  <span className="row-name">
                    <span className={`dot vendor-${vendorOf(m.model).key}`} aria-hidden="true" />
                    <span>
                      {m.model}
                      <small>{HARNESSES[m.harness] ?? m.harness}</small>
                    </span>
                  </span>
                </th>
                <td className="r">{pct(m.empty_rate)}</td>
                <td className="r">{pct(m.share_empty_drafts_with_no_pick)}</td>
                <td className="r">{pct(m.rate_ended_without_status_read)}</td>
                <td className="r">
                  {m.drafts_closed_holding_unused_pick} / {m.drafts}
                </td>
                <td className="r">{num(m.roster_at_end)}</td>
                <td className="r">{num(m.season_5_extensions_per_episode)}</td>
                <td className="r">
                  {m.episodes_final_below_after_season_4} / {m.episodes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="view-note">
        {data.models[0].phases} phases and {data.models[0].drafts} drafts per row, over {gap.seeds} games. Roster at end:
        players under contract after the final rollover, when the end-of-run terms are scored.
      </p>

      <h2>What this says about the benchmark</h2>
      <ul>
        <li>
          Our view: part of the season-5 run-down is our brief's wording. It describes the end-of-run term as "a capped
          credit for the roster, prospects, picks and cap health you leave behind". In score-v2 only cap room is capped;
          the roster, young-player, pick, strength and depth terms are not. The brief also does not say that contracts
          ending in season 5 leave before that credit is counted.
        </li>
        <li>
          The brief does not say that the rest of the regular season and the playoffs are played when the draft phase
          closes, or that a stored lineup stays in force and new players only fill empty slots. Several models act as if
          the season ended at the trade deadline.
        </li>
        <li>
          These are queued for the next contract in the{" "}
          <a href={`${REPO_BLOB}docs/bench_v2_1_queue.md`}>2.1 change queue</a>. The 2.1 contract is frozen, and its rows
          stand as measured: they were played and scored under the rules as written.
        </li>
      </ul>

      <h2>Caveats</h2>
      <ul>
        <li>
          Model and harness are confounded: every OpenAI row ran on {harnessesOf(openai)} and every Anthropic row on{" "}
          {harnessesOf(claude)}, so this cannot tell a model's habit from its harness's.
        </li>
        <li>
          This is a diagnostic, not a ranking. The standings still compare each row only with pick-trader.
        </li>
        {data.not_covered.length > 0 && (
          <li>
            {list(data.not_covered)} had no committed 2.1 row when the diagnostic ran, so they are not included.
          </li>
        )}
        <li>
          Every game of the {data.models.length} committed 2.1 rows was replayed with the frozen engine, with no model
          calls; each replayed final score and empty-phase count matches its row. Only aggregates are published.
        </li>
      </ul>

      <p className="view-note">
        <a href={`${REPO_BLOB}${data.source}`}>Diagnostic data</a> ·{" "}
        <a href={`${REPO_BLOB}${data.script}`}>Script that produced it</a>
      </p>
    </article>
  );
}
