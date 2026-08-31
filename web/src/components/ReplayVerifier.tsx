import { useEffect, useRef, useState } from "react";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "running" }
  | { kind: "success"; decisions: number; digest: string }
  | { kind: "error"; message: string };

type WorkerReply =
  | { type: "status"; status: "loading" | "running" }
  | { type: "success"; decisions: number; state_digest: string }
  | { type: "error"; message: string };

export default function ReplayVerifier() {
  const worker = useRef<Worker | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  useEffect(() => () => worker.current?.terminate(), []);

  const verify = () => {
    worker.current?.terminate();
    const next = new Worker(new URL("../replay/replayWorker.ts", import.meta.url), { type: "module" });
    worker.current = next;
    next.onmessage = (event: MessageEvent<WorkerReply>) => {
      const message = event.data;
      if (message.type === "status") setStatus({ kind: message.status });
      if (message.type === "success") {
        setStatus({ kind: "success", decisions: message.decisions, digest: message.state_digest });
        next.terminate();
      }
      if (message.type === "error") {
        setStatus({ kind: "error", message: message.message });
        next.terminate();
      }
    };
    next.onerror = () => {
      setStatus({ kind: "error", message: "The replay worker could not start. Try again online." });
      next.terminate();
    };
    setStatus({ kind: "loading" });
    next.postMessage({ type: "verify" });
  };

  const busy = status.kind === "loading" || status.kind === "running";
  const description =
    status.kind === "idle"
      ? "Runs one committed scripted episode in Python compiled to WebAssembly."
      : status.kind === "loading"
        ? "Loading the Python runtime (the first run can take a moment)…"
        : status.kind === "running"
          ? "Replaying the fixture and checking its final-state digest…"
          : status.kind === "success"
            ? `Verified ${status.decisions} decision windows. Digest ${status.digest.slice(0, 12)}…`
            : status.message;

  return (
    <div className="panel replay-check" aria-labelledby="replay-check-title">
      <div className="panel-title">
        <h3 id="replay-check-title">Try a browser replay</h3>
        <button type="button" className="copy-btn" onClick={verify} disabled={busy}>
          {busy ? "working…" : status.kind === "success" ? "run again" : "verify fixture"}
        </button>
      </div>
      <p aria-live="polite">{description}</p>
      {status.kind === "error" && <p className="replay-check-note">The rest of the site still works; this check needs the Pyodide files and fixture.</p>}
    </div>
  );
}
