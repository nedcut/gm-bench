import { useEffect, useRef, useState } from "react";
import { routes } from "../../site";

/* The 15-second promo, framed like a broadcast feed.
 *
 * Browsers only autoplay muted video, so it starts silent with a sound toggle.
 * Readers who ask for reduced motion get the poster and a play button instead,
 * and the loop pauses whenever it scrolls out of view. */

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function PromoVideo() {
  const video = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [reduced] = useState(prefersReducedMotion);

  useEffect(() => {
    const el = video.current;
    if (!el || reduced) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) el.play().catch(() => undefined);
        else el.pause();
      },
      { threshold: 0.25 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [reduced]);

  const toggleSound = () => {
    const el = video.current;
    if (!el) return;
    el.muted = !el.muted;
    setMuted(el.muted);
    // Turning sound on restarts the spot so the audio lands with its cues.
    if (!el.muted) {
      el.currentTime = 0;
      el.play().catch(() => undefined);
    }
  };

  const togglePlay = () => {
    const el = video.current;
    if (!el) return;
    if (el.paused) el.play().catch(() => undefined);
    else el.pause();
  };

  return (
    <figure className="promo">
      <div className="promo-frame">
        <video
          ref={video}
          className="promo-video"
          poster={`${routes.media}gm-bench-promo-poster.jpg`}
          muted
          loop
          playsInline
          preload={reduced ? "none" : "auto"}
          autoPlay={!reduced}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          aria-label="GM-Bench promo: a model runs a hockey front office, and every model trails the scripted pick-trader baseline."
        >
          <source src={`${routes.media}gm-bench-promo.webm`} type="video/webm" />
          <source src={`${routes.media}gm-bench-promo.mp4`} type="video/mp4" />
        </video>
        <div className="promo-bug" aria-hidden="true">
          <span className="promo-dot" /> GM-BENCH
        </div>
        <div className="promo-controls">
          <button type="button" onClick={togglePlay} aria-label={playing ? "Pause video" : "Play video"}>
            {playing ? "Pause" : "Play"}
          </button>
          <button type="button" onClick={toggleSound} aria-pressed={!muted}>
            {muted ? "Sound on" : "Mute"}
          </button>
        </div>
      </div>
    </figure>
  );
}
