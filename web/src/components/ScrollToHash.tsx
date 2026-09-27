import { useEffect } from "react";

/* Section ids render only after React mounts, so the browser's own jump to a
   URL fragment on a fresh load (a shared link, or the home page forwarding a
   legacy hash) finds nothing and leaves the reader at the top. Once the page
   commits, resolve the fragment ourselves, and keep looking for a short while
   in case the section renders a frame or two later. Same-page jumps after that
   are native anchor links against sections that already exist. */
const HASH_SCROLL_TIMEOUT_MS = 2000;

export default function ScrollToHash() {
  useEffect(() => {
    let id: string;
    try {
      id = decodeURIComponent(window.location.hash.slice(1));
    } catch {
      return; // A malformed fragment names no section.
    }
    if (!id) return;
    const deadline = performance.now() + HASH_SCROLL_TIMEOUT_MS;
    let frame = 0;
    let cancelled = false;
    let landedAt: number | null = null;
    const jump = (target: HTMLElement) => {
      target.scrollIntoView({ behavior: "instant", block: "start" });
      landedAt = window.scrollY;
    };
    // Late fonts or images above the section can push it down after the jump;
    // re-align once they settle, unless the reader has scrolled since.
    const realign = () => {
      const target = document.getElementById(id);
      if (!cancelled && target && landedAt !== null && Math.abs(window.scrollY - landedAt) < 2) {
        jump(target);
      }
    };
    const attempt = () => {
      const target = document.getElementById(id);
      if (target) {
        jump(target);
        void document.fonts?.ready.then(realign);
        if (document.readyState === "complete") realign();
        else window.addEventListener("load", realign, { once: true });
        return;
      }
      if (performance.now() < deadline) frame = requestAnimationFrame(attempt);
    };
    attempt();
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener("load", realign);
    };
  }, []);
  return null;
}
