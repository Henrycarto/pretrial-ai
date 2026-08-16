"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { CohortTable } from "@/components/ui/CohortTable";
import { PageHeader } from "@/components/ui/AppShell";
import { synthecore, type CohortSummary } from "@/lib/api";
import { cn, formatCount, formatPercent, gradeColor } from "@/lib/utils";

/**
 * Operations dashboard.
 *
 * The numbers along the top are the ones a clinical operations director
 * checks first thing: how many cohorts cleared validation, how many did not,
 * and what the median fidelity across the portfolio is. Everything below is
 * the list, worth scanning only after those four numbers raise a question.
 */
export default function DashboardPage() {
  const [cohorts, setCohorts] = useState<CohortSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    synthecore
      .jobs(100)
      .then((response) => {
        if (!cancelled) setCohorts(response.jobs);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "SyntheCore is unreachable.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const scored = (cohorts ?? []).filter(
    (cohort): cohort is CohortSummary & { overall_fidelity: number } =>
      typeof cohort.overall_fidelity === "number",
  );

  const passing = scored.filter((cohort) => cohort.overall_fidelity >= 90).length;
  const failing = scored.filter((cohort) => cohort.overall_fidelity < 70).length;
  const median = medianOf(scored.map((cohort) => cohort.overall_fidelity));
  const patients = (cohorts ?? []).reduce(
    (total, cohort) => total + (cohort.cohort_size ?? 0),
    0,
  );

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Cohort portfolio and validation status"
        actions={
          <Link href="/cohorts/new" className="btn btn-primary">
            new cohort
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-px border-b border-edge bg-edge lg:grid-cols-4">
        <Metric label="cohorts" value={formatCount(cohorts?.length ?? 0)} />
        <Metric
          label="median fidelity"
          value={median !== null ? formatPercent(median) : "n/a"}
          color={median !== null ? gradeColor(gradeFor(median)) : undefined}
        />
        <Metric
          label="validated"
          value={formatCount(passing)}
          color={passing > 0 ? "#10B981" : undefined}
        />
        <Metric
          label="below floor"
          value={formatCount(failing)}
          color={failing > 0 ? "#EF4444" : undefined}
        />
      </div>

      <div className="p-6">
        {error ? (
          <div className="panel px-4 py-4">
            <div className="label-micro mb-1.5 text-signal-fail">service unreachable</div>
            <p className="text-sm text-ink-muted">{error}</p>
            <p className="mt-3 text-xs text-ink-dim">
              Start the local stack with{" "}
              <span className="font-mono text-ink-muted">npm run stack:up</span>.
            </p>
          </div>
        ) : cohorts === null ? (
          <div className="panel px-4 py-6">
            <span className="label-micro">loading cohorts</span>
          </div>
        ) : (
          <>
            <div className="label-micro mb-3">recent cohorts</div>
            <CohortTable cohorts={cohorts.slice(0, 15)} />
            {cohorts.length > 15 && (
              <Link href="/cohorts" className="btn btn-ghost mt-3">
                view all {formatCount(cohorts.length)}
              </Link>
            )}
          </>
        )}

        <div className="mt-8">
          <div className="label-micro mb-3">patients generated</div>
          <div className="panel flex items-baseline gap-4 px-4 py-4">
            <span className="tabular text-3xl text-ink">{formatCount(patients)}</span>
            <span className="text-sm text-ink-muted">
              synthetic patients across all cohorts. None of them are real, and every
              exported record is tagged as test health data.
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

function Metric({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-surface px-5 py-4">
      <div className="label-micro mb-2">{label}</div>
      <div
        className={cn("tabular text-2xl", !color && "text-ink")}
        style={color ? { color } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

function medianOf(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[middle] ?? null;
  return ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

function gradeFor(score: number): "pass" | "borderline" | "fail" {
  if (score >= 90) return "pass";
  if (score >= 70) return "borderline";
  return "fail";
}
