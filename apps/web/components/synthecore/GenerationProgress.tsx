"use client";

import { useEffect, useRef, useState } from "react";
import type { CohortJob, JobStage } from "@pretrial/shared-types";

import { synthecore } from "@/lib/api";
import { cn, formatDuration, formatPercent } from "@/lib/utils";

/**
 * Live pipeline status for a running generation job.
 *
 * Not a spinner. A CTGAN fit runs for minutes, and a spinner over a four
 * minute wait tells the operator nothing except that the page has not
 * crashed. This renders the actual stage list with the running stage named,
 * its elapsed time counting, and the detail line the worker publishes, so
 * "still going" and "stuck" look different.
 *
 * Transport is Server Sent Events, fed from the Redis channel the Celery
 * worker publishes to. Two fallbacks exist because a progress view that
 * fails silently is worse than no progress view:
 *
 *   If the stream errors or the browser drops it, the component falls back
 *   to polling GET /jobs/{id}. Corporate proxies do sometimes buffer or kill
 *   long lived responses.
 *
 *   The server sends the current job state as the first frame, so a page
 *   opened partway through a job renders correctly instead of waiting for
 *   the next stage boundary.
 */

const POLL_INTERVAL_MS = 2500;
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

export interface GenerationProgressProps {
  jobId: string;
  onComplete?: (job: CohortJob) => void;
  className?: string;
}

export function GenerationProgress({
  jobId,
  onComplete,
  className,
}: GenerationProgressProps) {
  const [job, setJob] = useState<CohortJob | null>(null);
  const [transport, setTransport] = useState<"stream" | "polling" | "closed">("stream");
  const [error, setError] = useState<string | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    function settle(next: CohortJob) {
      if (cancelled) return;
      setJob(next);
      if (TERMINAL_STATUSES.has(next.status) && !completedRef.current) {
        completedRef.current = true;
        onComplete?.(next);
      }
    }

    function startPolling() {
      if (cancelled || pollTimer) return;
      setTransport("polling");
      pollTimer = setInterval(async () => {
        try {
          const next = await synthecore.job(jobId);
          settle(next);
          if (TERMINAL_STATUSES.has(next.status) && pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
            setTransport("closed");
          }
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "Lost contact with the job.");
        }
      }, POLL_INTERVAL_MS);
    }

    try {
      source = new EventSource(synthecore.streamUrl(jobId));

      source.addEventListener("progress", (event) => {
        try {
          settle(JSON.parse((event as MessageEvent).data) as CohortJob);
        } catch {
          // A malformed frame is not worth tearing the stream down for.
        }
      });

      source.addEventListener("close", () => {
        source?.close();
        if (!cancelled) setTransport("closed");
      });

      source.onerror = () => {
        source?.close();
        // EventSource fires onerror on normal close too, so polling only
        // starts if the job has not already reached a terminal state.
        if (!completedRef.current) startPolling();
      };
    } catch {
      startPolling();
    }

    return () => {
      cancelled = true;
      source?.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [jobId, onComplete]);

  if (error && !job) {
    return (
      <div className={cn("panel px-4 py-4", className)}>
        <div className="label-micro mb-2 text-signal-fail">connection lost</div>
        <p className="text-sm text-ink-muted">{error}</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className={cn("panel px-4 py-6", className)}>
        <div className="label-micro">connecting to job {jobId}</div>
      </div>
    );
  }

  return (
    <div className={cn("panel", className)}>
      <div className="panel-header">
        <div className="flex items-center gap-3">
          <StatusDot status={job.status} />
          <span className="font-mono text-xs uppercase tracking-[0.12em] text-ink">
            {job.status}
          </span>
          <span className="tabular text-xs text-ink-dim">{job.job_id}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="label-micro">{transport}</span>
          <span className="tabular text-sm text-ink">{formatPercent(job.percent, 0)}</span>
        </div>
      </div>

      {/* Overall bar. Squared off, one pixel of travel per percent, no
          animated shimmer. */}
      <div className="h-1 w-full bg-edge">
        <div
          className={cn(
            "h-full transition-[width] duration-500 ease-linear",
            job.status === "failed" ? "bg-signal-fail" : "bg-accent",
          )}
          style={{ width: `${Math.max(0, Math.min(100, job.percent))}%` }}
        />
      </div>

      <ol className="divide-y divide-edge-faint">
        {job.stages.map((stage, index) => (
          <StageRow key={stage.key} stage={stage} index={index} />
        ))}
      </ol>

      <div className="flex items-start justify-between gap-4 border-t border-edge bg-surface-sunken px-4 py-2.5">
        <span className="text-xs text-ink-muted">{job.message}</span>
        {job.result?.duration_seconds !== undefined && (
          <span className="tabular shrink-0 text-xs text-ink-dim">
            {formatDuration(job.result.duration_seconds)}
          </span>
        )}
      </div>

      {job.error && (
        <div className="border-t border-signal-fail bg-surface px-4 py-3">
          <div className="label-micro mb-1.5 text-signal-fail">{job.error.code}</div>
          <p className="text-sm text-ink">{job.error.message}</p>
        </div>
      )}
    </div>
  );
}

function StageRow({ stage, index }: { stage: JobStage; index: number }) {
  const elapsed = useElapsed(stage);

  const tone =
    stage.status === "done"
      ? "text-signal-pass"
      : stage.status === "running"
        ? "text-accent-bright"
        : stage.status === "failed"
          ? "text-signal-fail"
          : "text-ink-dim";

  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span className="tabular w-6 shrink-0 pt-0.5 text-xs text-ink-dim">
        {String(index + 1).padStart(2, "0")}
      </span>

      <StageMarker status={stage.status} />

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <span
            className={cn(
              "text-sm",
              stage.status === "pending" ? "text-ink-dim" : "text-ink",
            )}
          >
            {stage.label}
          </span>
          <span className={cn("tabular shrink-0 text-xs", tone)}>
            {stage.status === "pending" ? "queued" : elapsed}
          </span>
        </div>
        {stage.detail && (
          <p className="mt-1 truncate text-xs text-ink-muted">{stage.detail}</p>
        )}
      </div>
    </li>
  );
}

/**
 * Square markers, not circles or checkmark icons. The state is carried by
 * fill and colour, which stays legible at this size where a glyph does not.
 */
function StageMarker({ status }: { status: JobStage["status"] }) {
  const base = "mt-1 h-2.5 w-2.5 shrink-0 border";
  switch (status) {
    case "done":
      return <span className={cn(base, "border-signal-pass bg-signal-pass")} aria-hidden />;
    case "running":
      return (
        <span
          className={cn(base, "border-accent bg-accent motion-safe:animate-pulse")}
          aria-hidden
        />
      );
    case "failed":
      return <span className={cn(base, "border-signal-fail bg-signal-fail")} aria-hidden />;
    default:
      return <span className={cn(base, "border-edge-strong bg-transparent")} aria-hidden />;
  }
}

/** Ticks once a second while a stage runs, then freezes at its final duration. */
function useElapsed(stage: JobStage): string {
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    if (stage.status !== "running") return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [stage.status]);

  if (!stage.started_at) return "";
  const end = stage.finished_at ?? now;
  return formatDuration(Math.max(0, end - stage.started_at));
}

function StatusDot({ status }: { status: CohortJob["status"] }) {
  const color =
    status === "succeeded"
      ? "bg-signal-pass"
      : status === "failed" || status === "cancelled"
        ? "bg-signal-fail"
        : status === "running"
          ? "bg-accent motion-safe:animate-pulse"
          : "bg-ink-dim";
  return <span className={cn("h-2 w-2", color)} aria-hidden />;
}
