import { useLayoutEffect, useId, useRef } from "react";
import BrandMark from "./BrandMark";
import { createSkaters, FIXED_STEP, limitSpeed, moveHeld } from "./rinkPhysics";
import { advanceRink, decodeRink, FACEOFF_DELAY_MS, faceoff, GOAL_LEFT, GOAL_RIGHT, loadRink, newRinkGame, PUCK_INDEX, RINK_STORAGE_KEY, saveRink, scoreDroppedPuck, tracePuck, type RinkGame, type ScoringTeam } from "./rinkGame";

const STARTING_PLAYERS = createSkaters();

export default function RinkBoard() {
  const svgRef = useRef<SVGSVGElement>(null);
  const resetRef = useRef(() => {});
  const gameRef = useRef<RinkGame | null>(null);
  const confettiRef = useRef<SVGGElement>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const id = useId();

  useLayoutEffect(() => {
    const game = gameRef.current ??= loadRink();
    const svg = svgRef.current!;
    const bodies = game.bodies;
    const nodes = [...svg.querySelectorAll<SVGGElement>("[data-player]")];
    const transforms = nodes.map(node => node.getAttribute("transform"));
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0, previous = 0, accumulator = 0, visible = false;
    let savedAt = performance.now(), interactedAt = -Infinity;
    let hintTimer = 0, goalTimer = 0, faceoffTimer = 0;
    const confetti: Animation[] = [];
    let drag: {
      index: number; pointer: number; inverse: DOMMatrix;
      offsetX: number; offsetY: number; x: number; y: number; time: number;
    } | null = null;

    const movingNow = () => bodies.some((body, i) => i !== drag?.index && (body.vx !== 0 || body.vy !== 0));
    const persist = () => { saveRink(game); savedAt = performance.now(); };
    const onGoal = (team: ScoringTeam | null) => {
      if (!team) return;
      statusRef.current!.textContent = `Goal for ${team === "home" ? "Blue" : "Red"}!`;
      svg.dataset.goal = team;
      confetti.forEach(animation => animation.cancel());
      confetti.length = 0;
      confettiRef.current!.setAttribute("transform", `translate(160 ${team === "home" ? 58 : 412})`);
      if (!motion.matches) {
        [...confettiRef.current!.children].forEach((piece, i) => {
          const angle = i / 14 * Math.PI * 2;
          const dx = Math.cos(angle) * (28 + i % 3 * 8);
          const dy = Math.sin(angle) * (22 + i % 4 * 6);
          confetti.push(piece.animate([
            { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
            { transform: `translate(${dx}px, ${dy}px) rotate(${i % 2 ? 220 : -220}deg)`, opacity: 0 },
          ], { duration: 950, easing: "cubic-bezier(.12,.6,.4,1)" }));
        });
      }
      clearTimeout(goalTimer);
      goalTimer = window.setTimeout(() => { delete svg.dataset.goal; }, 1200);
      clearTimeout(faceoffTimer);
      faceoffTimer = window.setTimeout(dropPuck, FACEOFF_DELAY_MS);
      persist();
    };
    const dropPuck = () => {
      if (drag?.index === PUCK_INDEX) finish(true, false);
      faceoff(game);
      draw(); persist(); wake();
    };
    const tracePuckMove = (x: number, y: number) => {
      const result = tracePuck(game, x, y);
      onGoal(result.scored);
      return result.blocked;
    };
    const draw = () => {
      for (let i = 0; i < bodies.length; i++) {
        const body = bodies[i];
        const transform = `translate(${body.x.toFixed(2)} ${body.y.toFixed(2)})`;
        if (transforms[i] !== transform) {
          nodes[i].setAttribute("transform", transform);
          transforms[i] = transform;
        }
      }
    };
    const clearHint = () => {
      clearTimeout(hintTimer); hintTimer = 0;
      for (const node of nodes) node.classList.remove("is-hinting");
    };
    const scheduleHint = (delay = 1600) => {
      if (hintTimer || !visible || document.hidden || motion.matches) return;
      hintTimer = window.setTimeout(() => {
        hintTimer = 0;
        if (!drag && !movingNow() && performance.now() - interactedAt > 6000) {
          const index = Math.floor(Math.random() * 12);
          const angle = Math.random() * Math.PI * 2;
          nodes[index].classList.add("is-hinting");
          bodies[index].vx = Math.cos(angle) * 35;
          bodies[index].vy = Math.sin(angle) * 35;
          wake();
        }
        scheduleHint(5500 + Math.random() * 3500);
      }, delay);
    };
    const hintEnd = (event: AnimationEvent) => {
      if (event.animationName === "rink-wiggle") {
        (event.target as Element).closest("[data-player]")?.classList.remove("is-hinting");
      }
    };
    const interact = () => { interactedAt = performance.now(); clearHint(); scheduleHint(5500 + Math.random() * 3500); };
    const stop = () => {
      cancelAnimationFrame(frame);
      frame = previous = accumulator = 0;
    };
    const tick = (time: number) => {
      frame = 0;
      if (motion.matches) {
        previous = accumulator = 0;
        clearHint();
        for (const body of bodies) body.vx = body.vy = 0;
        draw(); persist();
        return;
      }
      accumulator += previous ? Math.min((time - previous) / 1000, 1 / 30) : FIXED_STEP;
      previous = time;
      let moving = movingNow();
      while (accumulator >= FIXED_STEP) {
        const result = advanceRink(game, FIXED_STEP, drag?.index);
        moving = result.moving;
        onGoal(result.scored);
        accumulator -= FIXED_STEP;
      }
      draw();
      if (performance.now() - savedAt > 1000 || !moving) persist();
      if (moving) frame = requestAnimationFrame(tick);
      else previous = accumulator = 0;
    };
    const wake = () => {
      if (frame || !visible || document.hidden || !movingNow()) return;
      if (motion.matches) {
        for (const body of bodies) body.vx = body.vy = 0;
        draw(); persist();
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    const playerIndex = (target: EventTarget | null) => {
      const node = target instanceof Element ? target.closest("[data-player]") : null;
      return node ? Number(node.getAttribute("data-player")) : -1;
    };
    const finish = (cancelled = false, saving = true) => {
      if (!drag) return;
      const body = bodies[drag.index];
      if (cancelled || performance.now() - drag.time > 100 || motion.matches) body.vx = body.vy = 0;
      if (!cancelled && drag.index === PUCK_INDEX) {
        onGoal(scoreDroppedPuck(game));
        if (game.puckInGoal && (game.puckInGoal === "home" ? body.y <= 62 : body.y >= 408)) body.locked = true;
      }
      nodes[drag.index].classList.remove("is-held");
      const pointer = drag.pointer;
      drag = null;
      if (svg.hasPointerCapture(pointer)) svg.releasePointerCapture(pointer);
      draw();
      if (saving) persist();
      wake();
    };
    const down = (event: PointerEvent) => {
      const index = playerIndex(event.target);
      if (index < 0 || drag || event.button !== 0) return;
      const inverse = svg.getScreenCTM()?.inverse();
      if (!inverse) return;
      event.preventDefault(); interact();
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(inverse);
      const body = bodies[index];
      body.vx = body.vy = 0;
      body.locked = false;
      drag = { index, pointer: event.pointerId, inverse,
        offsetX: point.x - body.x, offsetY: point.y - body.y,
        x: body.x, y: body.y, time: performance.now() };
      svg.setPointerCapture(event.pointerId);
      nodes[index].focus({ preventScroll: true });
      nodes[index].classList.add("is-held");
    };
    const move = (event: PointerEvent) => {
      if (!drag || event.pointerId !== drag.pointer) return;
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(drag.inverse);
      const body = bodies[drag.index];
      const time = performance.now();
      const dt = Math.max(0.008, (time - drag.time) / 1000);
      body.vx = (point.x - drag.offsetX - drag.x) / dt;
      body.vy = (point.y - drag.offsetY - drag.y) / dt;
      limitSpeed(body);
      moveHeld(bodies, drag.index, point.x - drag.offsetX, point.y - drag.offsetY, tracePuckMove);
      drag.x = body.x; drag.y = body.y; drag.time = time;
      draw();
      if (body.locked) finish(true);
      wake();
    };
    const up = (event: PointerEvent) => { if (event.pointerId === drag?.pointer) finish(); };
    const cancel = (event: PointerEvent) => { if (event.pointerId === drag?.pointer) finish(true); };
    const key = (event: KeyboardEvent) => {
      const index = playerIndex(event.target);
      if (index < 0 || drag) return;
      const directions: Record<string, [number, number]> = {
        ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
      };
      const body = bodies[index], direction = directions[event.key];
      const shoot = event.key === " " || event.key === "Enter";
      if (event.key === "Home") {
        event.preventDefault(); interact();
        body.vx = body.vy = 0; body.locked = false;
        if (index === PUCK_INDEX) game.puckInGoal = null;
        // Returning a skater can push the puck through a goal or into a net wall.
        moveHeld(bodies, index, body.homeX, body.homeY, index === PUCK_INDEX ? undefined : tracePuckMove);
      } else if (direction || shoot) {
        event.preventDefault(); interact();
        const [dx, dy] = direction ?? [0, body.team === "puck" ? (body.y < 235 ? -1 : 1) : body.team === "home" ? -1 : 1];
        body.locked = false;
        const throwing = (event.shiftKey || shoot) && !motion.matches;
        body.vx = dx * (throwing ? 650 : 0);
        body.vy = dy * (throwing ? 650 : 0);
        moveHeld(bodies, index, body.x + dx * 10, body.y + dy * 10, tracePuckMove);
        if (index === PUCK_INDEX) onGoal(scoreDroppedPuck(game));
      } else return;
      draw(); persist(); wake();
    };
    const suspend = () => { finish(true); stop(); clearHint(); persist(); };
    const visibility = () => {
      if (document.hidden) suspend(); else { wake(); scheduleHint(); }
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) { wake(); scheduleHint(); } else suspend();
    });
    const reducedMotion = () => {
      if (motion.matches) { stop(); clearHint(); confetti.forEach(animation => animation.cancel()); for (const body of bodies) body.vx = body.vy = 0; persist(); }
      else scheduleHint();
    };
    const storage = (event: StorageEvent) => {
      if (event.key !== RINK_STORAGE_KEY && event.key !== null) return;
      finish(true, false); stop(); clearHint();
      const incoming = decodeRink(event.newValue);
      incoming.bodies.forEach((body, i) => Object.assign(bodies[i], body, { vx: 0, vy: 0 }));
      game.score = incoming.score; game.puckInGoal = incoming.puckInGoal;
      draw(); scheduleHint();
    };
    // Back/forward cache can restore an old page without rerunning React effects.
    const pageshow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      stop(); clearHint();
      const incoming = loadRink();
      incoming.bodies.forEach((body, i) => Object.assign(bodies[i], body));
      game.score = incoming.score; game.puckInGoal = incoming.puckInGoal;
      draw(); wake(); scheduleHint();
    };
    const focus = () => { wake(); scheduleHint(); };
    resetRef.current = () => {
      interact(); finish(true); stop();
      clearTimeout(faceoffTimer);
      const fresh = newRinkGame();
      fresh.bodies.forEach((body, i) => Object.assign(bodies[i], body));
      game.score = fresh.score; game.puckInGoal = null;
      delete svg.dataset.goal;
      statusRef.current!.textContent = "Rink reset.";
      draw(); persist();
    };
    draw();
    observer.observe(svg);
    svg.addEventListener("pointerdown", down);
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerup", up);
    svg.addEventListener("pointercancel", cancel);
    svg.addEventListener("lostpointercapture", cancel);
    svg.addEventListener("keydown", key);
    svg.addEventListener("animationend", hintEnd);
    window.addEventListener("blur", suspend);
    window.addEventListener("resize", suspend);
    window.addEventListener("pagehide", suspend);
    window.addEventListener("pageshow", pageshow);
    window.addEventListener("focus", focus);
    window.addEventListener("storage", storage);
    document.addEventListener("visibilitychange", visibility);
    motion.addEventListener("change", reducedMotion);
    return () => {
      visible = false;
      suspend(); observer.disconnect(); clearTimeout(goalTimer); clearTimeout(faceoffTimer); confetti.forEach(animation => animation.cancel());
      svg.removeEventListener("pointerdown", down);
      svg.removeEventListener("pointermove", move);
      svg.removeEventListener("pointerup", up);
      svg.removeEventListener("pointercancel", cancel);
      svg.removeEventListener("lostpointercapture", cancel);
      svg.removeEventListener("keydown", key);
      svg.removeEventListener("animationend", hintEnd);
      window.removeEventListener("blur", suspend);
      window.removeEventListener("resize", suspend);
      window.removeEventListener("pagehide", suspend);
      window.removeEventListener("pageshow", pageshow);
      window.removeEventListener("focus", focus);
      window.removeEventListener("storage", storage);
      document.removeEventListener("visibilitychange", visibility);
      motion.removeEventListener("change", reducedMotion);
    };
  }, []);

  return (
    <div className="rink-playground">
      <p ref={statusRef} className="sr-only" role="status" aria-live="polite" />
      <div className="rink-surface">
      <svg ref={svgRef} className="rink-board" viewBox="0 0 320 470" role="group" aria-label="Interactive hockey rink" aria-describedby={`${id}-help`}>
        <defs><clipPath id={`${id}-ice`}><rect x="22" y="16" width="276" height="438" rx="78" /></clipPath></defs>
        <g aria-hidden="true">
          <rect className="rink-outer" x="16" y="10" width="288" height="450" rx="84" />
          <rect className="rink-ice" x="22" y="16" width="276" height="438" rx="78" />
          <g clipPath={`url(#${id}-ice)`} fill="none">
            <g className="rink-red" strokeWidth="1.4">
              <path d="M22 67H298M22 403H298" />
              {[108, 362].map(y => <g key={y}>{[90, 230].map(x => <g key={x}>
                <circle cx={x} cy={y} r="31" />
                <circle className="rink-dot" cx={x} cy={y} r="2.8" />
                <path d={`M${x - 35} ${y - 7}h8m-8 14h8M${x + 27} ${y - 7}h8m-8 14h8`} />
                <path d={`M${x - 8} ${y - 9}v6h-5m5 6v6h-5M${x + 8} ${y - 9}v6h5m-5 6v6h5`} />
              </g>)}</g>)}
              {[180, 290].map(y => [90, 230].map(x => <circle className="rink-dot" key={`${x}-${y}`} cx={x} cy={y} r="2.8" />))}
            </g>
            <g className="rink-blue" strokeWidth="3"><path d="M22 163H298M22 307H298" /></g>
            <path className="rink-red" d="M22 235H298" strokeWidth="2" />
            <g className="rink-blue" strokeWidth="1.5">
              <circle cx="160" cy="235" r="37" />
              <path className="rink-crease" d="M138 67a22 22 0 0 0 44 0ZM138 403a22 22 0 0 1 44 0Z" />
            </g>
            <g className="rink-net rink-net-home"><path d={`M${GOAL_LEFT} 67V47h${GOAL_RIGHT - GOAL_LEFT}v20`} /><path className="rink-net-mesh" d="M149 47v20m11-20v20m11-20v20M138 54h44m-44 7h44" /></g>
            <g className="rink-net rink-net-away"><path d={`M${GOAL_LEFT} 403v20h${GOAL_RIGHT - GOAL_LEFT}v-20`} /><path className="rink-net-mesh" d="M149 403v20m11-20v20m11-20v20M138 410h44m-44 7h44" /></g>
          </g>
          <BrandMark className="rink-center-logo" x={133} y={221} width={54} height={28} />
          <circle className="rink-center-dot" cx="160" cy="235" r="2" />
        </g>
        {STARTING_PLAYERS.map((body, i) => (
          <g className={`rink-player rink-player-${body.team}`} data-player={i} key={i}
            transform={`translate(${body.homeX} ${body.homeY})`} role="button" tabIndex={0}
            aria-label={`${body.team === "home" ? "Blue" : "Red"} ${body.label}, player ${i + 1}`}>
            <g className="rink-player-art"><circle r="14" /><text y="4" textAnchor="middle">{body.label}</text></g>
          </g>
        ))}
        <g className="rink-puck" data-player={PUCK_INDEX} transform="translate(160 255)" role="button" tabIndex={0} aria-label="Puck">
          <circle className="rink-puck-hit" r="13" /><circle className="rink-puck-disc" r="5" />
          <path d="M-2-2h3" />
        </g>
        <g ref={confettiRef} className="rink-confetti" transform="translate(160 58)" aria-hidden="true">
          {Array.from({ length: 14 }, (_, i) => <rect key={i} x={-2} y={-1.5} width="4" height="3" rx=".5" fill={["var(--bar)", "var(--rink-blue)", "#e5b64c"][i % 3]} />)}
        </g>
      </svg>
      <button type="button" className="rink-reset" onClick={() => resetRef.current()} aria-label="Reset rink" title="Reset rink">
        <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true"><path d="M4 7a6.5 6.5 0 1 1-.5 5M4 2.5V7h4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      </div>
      <div className="rink-controls">
        <span id={`${id}-help`}>Flick a player or puck to score<span className="sr-only">. Use arrow keys to move a focused player or puck, Shift plus arrow to throw, Space to shoot, and Home to return to its starting position. Blue scores in the top net; red in the bottom. Your rink is saved in this browser.</span></span>
      </div>
    </div>
  );
}
