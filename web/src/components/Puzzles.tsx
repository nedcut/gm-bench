import { useMemo, useState } from "react";
import type { Puzzle, PuzzleOption, PuzzleSet } from "../types";

/* Play the same decisions the policies faced.
 *
 * Every option on a card is a move some scripted policy actually made from this
 * exact observation, so there are no invented distractors. The grade is the
 * immediate change in score components -- deterministic, unlike replaying the
 * rest of the season, where within-seed noise swamps a single decision. */

const PHASE_BLURB: Record<string, string> = {
  preseason: "Free agency is open and the roster has to be legal before the season starts.",
  midseason: "About a third of the schedule has played. Injuries have landed and rivals have waived players.",
  trade_deadline: "Last chance to deal with the other eleven front offices this season.",
  draft: "A seeded prospect class is on the board and your pick is in.",
};

function verdictFor(picked: PuzzleOption, best: PuzzleOption): string {
  const gap = best.immediate_score - picked.immediate_score;
  if (gap <= 0.001) return "Best call on the board.";
  if (gap < 1) return "Line ball, a fraction behind the best call.";
  if (gap < 5) return "Reasonable, but there was more on the table.";
  return "The board had a much better move.";
}

function subjectChoice(puzzle: Puzzle): PuzzleOption | undefined {
  return puzzle.options.find((option) => option.chosen_by.includes(puzzle.subject));
}

function subjectMargin(puzzle: Puzzle, best: PuzzleOption): number | null {
  if (puzzle.subject_margin !== undefined) return puzzle.subject_margin;
  const choice = subjectChoice(puzzle);
  if (choice) return choice.immediate_score - best.immediate_score;
  if (puzzle.points_left_on_the_table !== undefined) return -puzzle.points_left_on_the_table;
  return null;
}

function subjectOutcome(puzzle: Puzzle, margin: number | null): "subject_won" | "subject_missed" | null {
  if (puzzle.outcome) return puzzle.outcome;
  if (margin === null) return null;
  return margin >= -0.001 ? "subject_won" : "subject_missed";
}

function Scoreline({ answered, matched, dropped }: { answered: number; matched: number; dropped: number }) {
  return (
    <dl className="puzzle-score" aria-label="Your running tally">
      <div>
        <dt>Decisions</dt>
        <dd>{answered}</dd>
      </div>
      <div>
        <dt>Best call found</dt>
        <dd>
          {matched}
          <span className="puzzle-score-sub"> of {answered}</span>
        </dd>
      </div>
      <div>
        <dt>Left on the table</dt>
        <dd>{dropped.toFixed(1)}</dd>
      </div>
    </dl>
  );
}

function Card({
  puzzle,
  picked,
  onPick,
}: {
  puzzle: Puzzle;
  picked: string | null;
  onPick: (id: string) => void;
}) {
  const { situation } = puzzle;
  const best = puzzle.options.find((option) => option.id === puzzle.answer) ?? puzzle.options[0];
  const revealed = picked !== null;
  const subject = subjectChoice(puzzle);
  const margin = subjectMargin(puzzle, best);
  const outcome = subjectOutcome(puzzle, margin);

  return (
    <div className="puzzle-card">
      <div className="puzzle-situation">
        <div>
          <p className="kicker">
            Season {situation.season} · {situation.phase}
          </p>
          <h3>{situation.team}</h3>
          <p className="puzzle-blurb">{PHASE_BLURB[puzzle.phase] ?? ""}</p>
        </div>
        <dl className="puzzle-facts">
          <div>
            <dt>Record</dt>
            <dd>{situation.record}</dd>
          </div>
          <div>
            <dt>Cap room</dt>
            <dd>${situation.cap_room.toFixed(1)}M</dd>
          </div>
          <div>
            <dt>Roster</dt>
            <dd>{situation.roster_size}</dd>
          </div>
          {situation.offers_on_the_table > 0 && (
            <div>
              <dt>Offers in</dt>
              <dd>{situation.offers_on_the_table}</dd>
            </div>
          )}
        </dl>
      </div>

      <ul className="puzzle-options">
        {puzzle.options.map((option) => {
          const isPicked = option.id === picked;
          const isBest = option.id === puzzle.answer;
          const classes = ["puzzle-option"];
          if (revealed && isBest) classes.push("is-best");
          if (revealed && isPicked && !isBest) classes.push("is-picked");
          return (
            <li key={option.id}>
              <button
                type="button"
                className={classes.join(" ")}
                onClick={() => onPick(option.id)}
                disabled={revealed}
                aria-pressed={isPicked}
              >
                <span className="puzzle-option-mark" aria-hidden="true">
                  {option.id.toUpperCase()}
                </span>
                <span className="puzzle-option-body">
                  {option.lines.map((line, lineIndex) => (
                    <span key={`${option.id}-${lineIndex}`} className="puzzle-line">
                      {line}
                    </span>
                  ))}
                  {revealed && (
                    <span className="puzzle-reveal">
                      <b>{option.immediate_score >= 0 ? "+" : ""}
                        {option.immediate_score.toFixed(2)}</b> · {option.summary}
                      <span className="puzzle-chosen">
                        played by {option.chosen_by.join(", ")}
                      </span>
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {revealed && (
        <p className="puzzle-verdict">
          {verdictFor(puzzle.options.find((o) => o.id === picked) ?? best, best)}{" "}
          <span className="puzzle-verdict-sub">
            {subject ? (
              <>
                The <code>{puzzle.subject}</code> policy took {subject.id.toUpperCase()} here. {" "}
                {outcome === "subject_won" && margin !== null
                  ? margin > 0.001
                    ? `It beat the other recorded choices by ${margin.toFixed(1)} points on the immediate score proxy.`
                    : "It matched the best recorded choice on the immediate score proxy."
                  : outcome === "subject_missed" && margin !== null
                    ? `It left ${Math.abs(margin).toFixed(1)} points of immediate roster value on the table against the best recorded choice.`
                    : "Its result is not classified in this fixture."}
              </>
            ) : (
              <>The subject policy's recorded choice is not identified in this fixture.</>
            )}
          </span>
        </p>
      )}
    </div>
  );
}

export default function Puzzles({ data }: { data: PuzzleSet }) {
  const puzzles = data.puzzles;
  const [index, setIndex] = useState(0);
  const [picks, setPicks] = useState<Record<string, string>>({});

  const tally = useMemo(() => {
    let matched = 0;
    let dropped = 0;
    let answered = 0;
    for (const puzzle of puzzles) {
      const pick = picks[puzzle.id];
      if (!pick) continue;
      answered += 1;
      const chosen = puzzle.options.find((option) => option.id === pick);
      const best = puzzle.options.find((option) => option.id === puzzle.answer);
      if (!chosen || !best) continue;
      if (pick === puzzle.answer) matched += 1;
      dropped += Math.max(0, best.immediate_score - chosen.immediate_score);
    }
    return { matched, dropped, answered };
  }, [picks, puzzles]);

  if (puzzles.length === 0) return null;
  const puzzle = puzzles[index];
  const picked = picks[puzzle.id] ?? null;
  const last = index === puzzles.length - 1;

  return (
    <section className="section" id="play" tabIndex={-1}>
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Play along</p>
          <h2>You make the call</h2>
          <p>
            Real decisions from recorded episodes. Every option is a move some policy actually made
            from this same information. Nothing here is invented. Options are graded on what they do
            to the roster immediately with a deterministic score proxy, so the result does not depend
            on how the rest of the season happens to play out.
          </p>
        </div>

        {tally.answered > 0 && (
          <Scoreline answered={tally.answered} matched={tally.matched} dropped={tally.dropped} />
        )}

        <Card
          puzzle={puzzle}
          picked={picked}
          onPick={(id) => setPicks((current) => ({ ...current, [puzzle.id]: id }))}
        />

        <div className="puzzle-controls">
          <span className="puzzle-progress">
            {index + 1} / {puzzles.length}
          </span>
          <div className="puzzle-buttons">
            <button type="button" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0}>
              Back
            </button>
            <button
              type="button"
              className="is-primary"
              onClick={() => setIndex((i) => Math.min(puzzles.length - 1, i + 1))}
              disabled={last}
            >
              {picked ? "Next decision" : "Skip"}
            </button>
          </div>
        </div>

        <p className="puzzle-note">{data.note}</p>
      </div>
    </section>
  );
}
