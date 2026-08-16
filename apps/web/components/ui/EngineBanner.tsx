"use client";

import { useEffect, useState } from "react";

import { synthecore } from "@/lib/api";

/**
 * States plainly which generation engine the deployment is running.
 *
 * A cohort from the bootstrap stub and a cohort from CTGAN are not
 * interchangeable, and the difference has to be visible on screen rather
 * than buried in an environment variable. Anyone screenshotting this UI for
 * a deck should not be able to accidentally present stub output as
 * production output.
 */
export function EngineBanner() {
  const [engine, setEngine] = useState<{
    engine: string;
    is_stub: boolean;
    method: string;
  } | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    synthecore
      .engine()
      .then((info) => {
        if (!cancelled) setEngine(info);
      })
      .catch(() => {
        if (!cancelled) setUnreachable(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (unreachable) {
    return (
      <div className="flex items-center gap-3 border-b border-edge bg-surface-sunken px-6 py-1.5">
        <span className="h-1.5 w-1.5 bg-signal-fail" aria-hidden />
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-signal-fail">
          SyntheCore unreachable
        </span>
        <span className="text-[11px] text-ink-dim">
          Start the local stack with npm run stack:up
        </span>
      </div>
    );
  }

  if (!engine) return <div className="h-[29px] border-b border-edge bg-surface-sunken" />;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-edge bg-surface-sunken px-6 py-1.5">
      <span
        className={`h-1.5 w-1.5 ${engine.is_stub ? "bg-signal-warn" : "bg-signal-pass"}`}
        aria-hidden
      />
      <span
        className={`font-mono text-[10px] uppercase tracking-[0.12em] ${
          engine.is_stub ? "text-signal-warn" : "text-signal-pass"
        }`}
      >
        engine {engine.engine}
      </span>
      <span className="text-[11px] text-ink-dim">
        {engine.is_stub
          ? "Placeholder generator. Output is for pipeline demonstration and carries no privacy guarantee."
          : engine.method}
      </span>
    </div>
  );
}
