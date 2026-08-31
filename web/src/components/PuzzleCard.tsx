import { useState } from "react";
import type { Puzzle, PuzzleOption } from "../types";

/* One decision card, playable in place.
 *
 * Every option is a move some scripted policy actually made from this exact
 * observation, so there are no invented distractors. The grade is the immediate
 * change in score components -- deterministic, unlike replaying the rest of the
 * season, where within-seed noise swamps a single decision.
 *
 * These used to be a standalone deck. They now sit inside the replay view, next
 * to the phase they describe, so the question and the recorded episode share a
 * context instead of competing for the reader's attention. */

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

/* The stored `subject_margin` measures the subject's choice against the best
 * *alternative* recorded choice, which is why it can be positive. Comparing
 * against the best option overall would score the subject's own pick against
 * itself and could never come out ahead, so the fallback measures the same
 * quantity the fixture stores. */
function subjectMargin(puzzle: Puzzle): number | null {
  if (puzzle.subject_margin !== undefined) return puzzle.subject_margin;
  const choice = subjectChoice(puzzle);
  if (choice) {
    const alternatives = puzzle.options.filter((option) => option.id !== choice.id);
    if (alternatives.length === 0) return null;
    const bestAlternative = Math.max(...alternatives.map((option) => option.immediate_score));
    return choice.immediate_score - bestAlternative;
  }
  if (puzzle.points_left_on_the_table !== undefined) return -puzzle.points_left_on_the_table;
  return null;
}

function subjectOutcome(
  puzzle: Puzzle,
  margin: number | null,
): "subject_won" | "subject_missed" | null {
  if (puzzle.outcome) return puzzle.outcome;
  if (margin === null) return null;
  return margin >= -0.001 ? "subject_won" : "subject_missed";
}

export default function PuzzleCard({ puzzle }: { puzzle: Puzzle }) {
  const [picked, setPicked] = useState<string | null>(null);
  const { situation } = puzzle;
  const best = puzzle.options.find((option) => option.id === puzzle.answer) ?? puzzle.options[0];
  const revealed = picked !== null;
  const subject = subjectChoice(puzzle);
  const margin = subjectMargin(puzzle);
  const outcome = subjectOutcome(puzzle, margin);

  return (
    <div className="puzzle-card">
      <div className="puzzle-situation">
        <div>
          <p className="kicker">
            Season {situation.season} · {situation.phase.replace(/_/g, " ")} · seed{" "}
            {puzzle.seed}
          </p>
          <h3>{situation.team}</h3>
          <p className="puzzle-blurb">
            Recorded from the <code>{puzzle.subject}</code> policy. Pick the move you would
            make.
          </p>
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
                onClick={() => setPicked(option.id)}
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
                      <b>
                        {option.immediate_score >= 0 ? "+" : ""}
                        {option.immediate_score.toFixed(2)}
                      </b>{" "}
                      · {option.summary}
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
                The <code>{puzzle.subject}</code> policy took {subject.id.toUpperCase()} here.{" "}
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
