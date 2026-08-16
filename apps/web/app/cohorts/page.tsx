"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { CohortTable } from "@/components/ui/CohortTable";
import { PageHeader } from "@/components/ui/AppShell";
import { synthecore, type CohortSummary } from "@/lib/api";
import { cn, formatCount } from "@/lib/utils";

type Filter = "all" | "validated" | "borderline" | "failed" | "running";

export default function CohortsPage() {
  const [cohorts, setCohorts] = useState<CohortSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    synthecore
      .jobs(500)
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

  const visible = useMemo(() => {
    const list = cohorts ?? [];
    return list.filter((cohort) => {
      if (query && !cohort.job_id.includes(query.trim())) return false;
      const score = cohort.overall_fidelity;
      switch (filter) {
        case "validated":
          return score !== null && score >= 90;
        case "borderline":
          return score !== null && score >= 70 && score < 90;
        case "failed":
          return cohort.status === "failed" || (score !== null && score < 70);
        case "running":
          return cohort.status === "running" || cohort.status === "queued";
        default:
          return true;
      }
    });
  }, [cohorts, filter, query]);

  return (
    <>
      <PageHeader
        title="Cohorts"
        subtitle="Every generation run, newest first"
        actions={
          <Link href="/cohorts/new" className="btn btn-primary">
            new cohort
          </Link>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-edge bg-surface px-6 py-3">
        <div className="flex flex-wrap gap-1">
          {(
            [
              ["all", "all"],
              ["validated", "validated"],
              ["borderline", "borderline"],
              ["failed", "failed"],
              ["running", "running"],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={cn(
                "border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
                filter === key
                  ? "border-accent text-accent-bright"
                  : "border-edge text-ink-dim hover:border-edge-strong hover:text-ink-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <input
          className="field-mono w-56"
          placeholder="filter by cohort id"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Filter by cohort id"
        />
      </div>

      <div className="p-6">
        {error ? (
          <div className="panel px-4 py-4">
            <div className="label-micro mb-1.5 text-signal-fail">service unreachable</div>
            <p className="text-sm text-ink-muted">{error}</p>
          </div>
        ) : cohorts === null ? (
          <div className="panel px-4 py-6">
            <span className="label-micro">loading cohorts</span>
          </div>
        ) : (
          <>
            <div className="label-micro mb-3">
              {formatCount(visible.length)} of {formatCount(cohorts.length)}
            </div>
            <CohortTable
              cohorts={visible}
              emptyMessage={
                cohorts.length === 0
                  ? "No cohorts have been generated yet."
                  : "No cohorts match this filter."
              }
            />
          </>
        )}
      </div>
    </>
  );
}
