import { useEffect, useMemo, useState } from "react";
import type { Leaderboard as LeaderboardData } from "../types";
import { fmt } from "../lib";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function useTypedLines(lines: string[], enabled: boolean) {
  const [lineIndex, setLineIndex] = useState(0);
  const [charIndex, setCharIndex] = useState(0);
  const [done, setDone] = useState(!enabled);

  useEffect(() => {
    if (!enabled) {
      setDone(true);
      return;
    }
    if (lineIndex >= lines.length) {
      setDone(true);
      return;
    }
    const current = lines[lineIndex];
    if (charIndex >= current.length) {
      const timer = window.setTimeout(() => {
        setLineIndex((value) => value + 1);
        setCharIndex(0);
      }, 120);
      return () => window.clearTimeout(timer);
    }
    const timer = window.setTimeout(() => {
      setCharIndex((value) => value + 1);
    }, current.startsWith("//") ? 10 : 16);
    return () => window.clearTimeout(timer);
  }, [charIndex, enabled, lineIndex, lines]);

  const visible = lines.slice(0, lineIndex).concat(
    lineIndex < lines.length ? [lines[lineIndex].slice(0, charIndex)] : [],
  );
  return { visible, done };
}

function renderLine(line: string, key: number) {
  if (line.startsWith("//")) {
    return (
      <div key={key} className="term-line">
        <span className="t-dim">{line}</span>
      </div>
    );
  }
  if (line.startsWith("$ ")) {
    return (
      <div key={key} className="term-line">
        <span className="t-prompt">$ </span>
        <span className="t-cmd">{line.slice(2)}</span>
      </div>
    );
  }
  if (line.startsWith("    --")) {
    const [flag, ...rest] = line.trim().split(" ");
    return (
      <div key={key} className="term-line">
        <span className="t-flag">    {flag} </span>
        <span className="t-num">{rest.join(" ")}</span>
      </div>
    );
  }
  const eq = line.indexOf(" = ");
  if (eq > 0) {
    return (
      <div key={key} className="term-line">
        <span className="t-key">{line.slice(0, eq)} </span>
        <span className="t-out">= </span>
        <span className="t-num">{line.slice(eq + 3)}</span>
      </div>
    );
  }
  return (
    <div key={key} className="term-line">
      <span className="t-out">{line || "\u00a0"}</span>
    </div>
  );
}

export default function Hero({ leaderboard }: { leaderboard: LeaderboardData }) {
  const reducedMotion = usePrefersReducedMotion();
  const pickTrader = leaderboard.baselines.find((row) => row.agent === "pick-trader");
  const bestModel = [...leaderboard.models].sort((a, b) => b.mean_score - a.mean_score)[0];
  const bar = pickTrader?.mean_score ?? 0;
  const gap = bestModel ? bestModel.mean_score - bar : null;

  const lines = useMemo(() => {
    const next = [
      "// scripted bar to beat",
      `pick-trader = ${fmt(bar, 1)}`,
      "",
      "// best model on this board",
    ];
    if (bestModel && gap !== null) {
      next.push(
        `${bestModel.model.slice(0, 14)} = ${fmt(bestModel.mean_score, 1)}`,
        `vs pick-trader = ${gap >= 0 ? "+" : ""}${fmt(gap, 1)}`,
        "",
        gap >= 0
          ? "// honest read: a model has cleared the bar"
          : "// honest read: models are still below the bar",
      );
    } else {
      next.push("// no model rows yet — submit a run");
    }
    next.push("", "$ python -m gm_bench model", "    --preset leaderboard --repeats 3");
    return next;
  }, [bar, bestModel, gap]);

  const { visible, done } = useTypedLines(lines, !reducedMotion);

  return (
    <section className="hero" id="top">
      <div className="hero-glow" />
      <div className="hero-grid-lines" />
      <div className="hero-orb hero-orb-a" aria-hidden="true" />
      <div className="hero-orb hero-orb-b" aria-hidden="true" />
      <div className="shell hero-inner">
        <div className="hero-copy">
          <span className="hero-kicker">
            <i className="dot" />
            Long-horizon · Seeded · JSON protocol
          </span>
          <p className="hero-brand">GM-Bench</p>
          <h1>
            Can your agent run a <span className="grad">franchise front office</span>?
          </h1>
          <p className="hero-sub">
            Multi-season GM decisions under uncertainty: contracts, trades, drafts, cap
            pressure, and lineups. Fictional players. Deterministic seeds. Scores that
            measure strategy — not luck or UI automation.
          </p>
          <div className="hero-actions">
            <a className="btn-primary" href="#quickstart">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
              Run the benchmark
            </a>
            <a className="btn-ghost" href="#leaderboard">
              See the bar to beat
            </a>
          </div>
        </div>

        <div className="terminal hero-terminal" aria-label="Official bar to beat">
          <div className="terminal-bar">
            <i /><i /><i />
            <span>
              official panel · {leaderboard.preset.seeds.length} seeds × {leaderboard.preset.seasons}{" "}
              seasons
            </span>
          </div>
          <div className="terminal-body">
            {(reducedMotion ? lines : visible).map((line, index) => renderLine(line, index))}
            {!done && <span className="term-caret" aria-hidden="true" />}
          </div>
        </div>
      </div>
    </section>
  );
}
