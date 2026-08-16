"use client";

import Link from "next/link";

import { FidelityScoreInline } from "@/components/fidelity/FidelityScoreBadge";
import type { CohortSummary } from "@/lib/api";
import { cn, formatCount, formatDuration, formatTimestamp } from "@/lib/utils";

/**
 * The cohort list.
 *
 * A table, not a grid of cards. Cohorts are compared against each other on
 * fidelity, size, and age, and a table is the only layout where a director
 * can scan one column down thirty rows. Fidelity leads because it is the
 * column that decides which rows matter.
 */
export function CohortTable({
  cohorts,
  emptyMessage = "No cohorts yet.",
  className,
}: {
  cohorts: CohortSummary[];
  emptyMessage?: string;
  className?: string;
}) {
  if (cohorts.length === 0) {
    return (
      <div className={cn("panel px-4 py-8 text-center", className)}>
        <p className="text-sm text-ink-muted">{emptyMessage}</p>
        <Link href="/cohorts/new" className="btn btn-primary mt-4">
          build a cohort
        </Link>
      </div>
    );
  }

  return (
    <div className={cn("panel overflow-x-auto", className)}>
      <table className="data-table">
        <thead>
          <tr>
            <th className="text-right">fidelity</th>
            <th>cohort</th>
            <th>status</th>
            <th className="text-right">patients</th>
            <th className="text-right">features</th>
            <th>engine</th>
            <th className="text-right">runtime</th>
            <th className="text-right">created</th>
          </tr>
        </thead>
        <tbody>
          {cohorts.map((cohort) => (
            <tr key={cohort.job_id}>
              <td className="text-right">
                {cohort.overall_fidelity !== null ? (
                  <FidelityScoreInline
                    score={cohort.overall_fidelity}
                    grade={cohort.grade ?? undefined}
                    className="justify-end"
                  />
                ) : (
                  <span className="text-xs text-ink-dim">not scored</span>
                )}
              </td>
              <td>
                <Link
                  href={`/cohorts/${cohort.job_id}`}
                  className="font-mono text-[13px] text-ink hover:text-accent-bright"
                >
                  {cohort.job_id}
                </Link>
                {cohort.status !== "succeeded" && cohort.stage_label && (
                  <span className="ml-2 text-xs text-ink-dim">{cohort.stage_label}</span>
                )}
              </td>
              <td>
                <StatusPill status={cohort.status} percent={cohort.percent} />
              </td>
              <td className="tabular text-right text-[13px] text-ink-muted">
                {cohort.cohort_size !== null ? formatCount(cohort.cohort_size) : ""}
              </td>
              <td className="tabular text-right text-[13px] text-ink-dim">
                {cohort.features || ""}
              </td>
              <td>
                <span className="font-mono text-[11px] text-ink-dim">
                  {cohort.engine ?? ""}
                </span>
                {cohort.is_stub && (
                  <span className="ml-1.5 border border-signal-warn px-1 py-0.5 font-mono text-[9px] uppercase text-signal-warn">
                    stub
                  </span>
                )}
              </td>
              <td className="tabular text-right text-[13px] text-ink-dim">
                {cohort.duration_seconds !== null
                  ? formatDuration(cohort.duration_seconds)
                  : ""}
              </td>
              <td className="tabular text-right text-[11px] text-ink-dim">
                {formatTimestamp(cohort.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusPill({
  status,
  percent,
}: {
  status: CohortSummary["status"];
  percent: number;
}) {
  const tone =
    status === "succeeded"
      ? "border-signal-pass text-signal-pass"
      : status === "failed" || status === "cancelled"
        ? "border-signal-fail text-signal-fail"
        : status === "running"
          ? "border-accent text-accent-bright"
          : "border-edge-strong text-ink-dim";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em]",
        tone,
      )}
    >
      {status}
      {status === "running" && (
        <span className="tabular">{Math.round(percent)}%</span>
      )}
    </span>
  );
}
