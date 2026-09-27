import { useState } from "react";
import type { PuzzleSet } from "../../types";
import PuzzleCard from "../PuzzleCard";

const MECHANIC_LABEL: Record<string, string> = {
  trade: "Trade",
  draft: "Draft",
  free_agency: "Free agency",
};

/* The deck: real decisions from recorded episodes, one at a time, with a
   running count of how often the reader found the best recorded move. */
export default function PlayAlong({ set }: { set: PuzzleSet }) {
  const deck = set.puzzles;
  const [index, setIndex] = useState(0);
  // Each card's pick and its verdict, so a card restores the reader's answer
  // when they come back to it and the tally always counts that same pick.
  const [results, setResults] = useState<Record<string, { optionId: string; isBest: boolean }>>({});
  const puzzle = deck[index];
  if (!puzzle) return null;

  const played = Object.keys(results).length;
  const best = Object.values(results).filter((result) => result.isBest).length;
  const answered = puzzle.id in results;
  const go = (step: number) => setIndex((i) => (i + step + deck.length) % deck.length);

  return (
    <section className="play" id="play" tabIndex={-1} aria-labelledby="play-title">
      <div className="shell play-inner">
        <div className="play-copy">
          <p className="eyebrow">Play along</p>
          <h2 id="play-title" className="display-2">
            Your call, GM.
          </h2>
          <p>
            {deck.length} real decisions pulled from recorded episodes. Every option is a move some
            scripted policy actually made from that exact spot, with no invented distractors. Pick
            one and see what each move did to the roster.
          </p>
          <p className="play-note">
            Graded on the immediate change to the roster, because a single season is mostly luck.
            It is a teaching aid, not a benchmark result.
          </p>
          <div className="play-tally" aria-live="polite">
            <span className="play-tally-num">
              {best}
              <small>/{played}</small>
            </span>
            <span>best calls so far</span>
          </div>
        </div>
        <div className="play-deck">
          <div className="play-bar">
            <span className="chip">{MECHANIC_LABEL[puzzle.mechanic ?? ""] ?? puzzle.phase.replace(/_/g, " ")}</span>
            <span className="mono play-count">
              {index + 1} / {deck.length}
            </span>
            <div className="play-nav">
              <button type="button" onClick={() => go(-1)} aria-label="Previous decision">
                ←
              </button>
              <button
                type="button"
                className={answered ? "is-ready" : undefined}
                onClick={() => go(1)}
                aria-label="Next decision"
              >
                Next →
              </button>
            </div>
          </div>
          <PuzzleCard
            key={puzzle.id}
            puzzle={puzzle}
            initialPick={results[puzzle.id]?.optionId ?? null}
            onPick={(isBest, optionId) =>
              setResults((r) => (puzzle.id in r ? r : { ...r, [puzzle.id]: { optionId, isBest } }))
            }
          />
        </div>
      </div>
    </section>
  );
}
