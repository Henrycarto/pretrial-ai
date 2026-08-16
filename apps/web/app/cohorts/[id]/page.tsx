"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { CohortJob } from "@pretrial/shared-types";

import { ExportPanel } from "@/components/fhirlink/ExportPanel";
import { FidelityScoreBadge } from "@/components/fidelity/FidelityScoreBadge";
import { GenerationProgress } from "@/components/synthecore/GenerationProgress";
import { PageHeader } from "@/components/ui/AppShell";
import { synthecore } from "@/lib/api";
import { cn, formatCount, formatDuration, formatPercent } from "@/lib/utils";

/**
 * A single cohort.
 *
 * If the job is still running this renders the live pipeline instead of an
 * empty shell, so the URL is shareable the moment the job is queued rather
 * than only after it finishes.
 */
export default function CohortPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;

  const [job, setJob] = useState<CohortJob | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"summary" | "screening" | "cohort" | "export">("summary");

  useEffect(() => {
    let cancelled = false;
    synthecore
      .job(jobId)
      .then((next) => {
        if (!cancelled) setJob(next);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Cohort not found.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (job?.status !== "succeeded") return;
    let cancelled = false;
    synthecore
      .cohort(jobId, 500)
      .then((response) => {
        if (!cancelled) setRows(response.rows);
      })
      .catch(() => {
        // The cohort rows expiring from storage is not a page level failure.
        // The summary and the validation report are still worth showing.
      });
    return () => {
      cancelled = true;
    };
  }, [job?.status, jobId]);

  if (error) {
    return (
      <>
        <PageHeader title="Cohort not found" subtitle={jobId} />
        <div className="p-6">
          <div className="panel px-4 py-4">
            <p className="text-sm text-ink-muted">{error}</p>
            <Link href="/cohorts" className="btn btn-secondary mt-4">
              back to cohorts
            </Link>
          </div>
        </div>
      </>
    );
  }

  if (!job) {
    return (
      <>
        <PageHeader title="Cohort" subtitle={jobId} />
        <div className="p-6">
          <div className="panel px-4 py-6">
            <span className="label-micro">loading</span>
          </div>
        </div>
      </>
    );
  }

  if (job.status !== "succeeded") {
    return (
      <>
        <PageHeader title="Cohort generation" subtitle={jobId} />
        <div className="p-6">
          <GenerationProgress jobId={jobId} onComplete={setJob} />
        </div>
      </>
    );
  }

  const result = job.result;
  const validation = result?.validation;
  const fidelity = validation?.overall_fidelity;

  return (
    <>
      <PageHeader
        title={result?.seed_profile.source ? "Cohort" : "Cohort"}
        subtitle={jobId}
        actions={
          validation?.status === "complete" && (
            <Link href={`/validation/${jobId}`} className="btn btn-secondary">
              full validation report
            </Link>
          )
        }
      />

      <div className="border-b border-edge bg-surface">
        <div className="flex flex-col gap-8 px-6 py-6 lg:flex-row lg:items-center">
          <FidelityScoreBadge
            score={fidelity}
            grade={validation?.grade}
            size="lg"
          />

          <div className="min-w-0 flex-1">
            <div className="grid grid-cols-2 gap-px border border-edge bg-edge sm:grid-cols-4">
              <Stat label="cohort size" value={formatCount(result?.cohort_size)} />
              <Stat label="requested" value={formatCount(result?.requested_size)} />
              <Stat label="features" value={formatCount(result?.features.length)} />
              <Stat
                label="generation time"
                value={formatDuration(result?.duration_seconds)}
              />
            </div>

            {validation?.verdict && (
              <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink-muted">
                {validation.verdict}
              </p>
            )}

            {validation?.status !== "complete" && (
              <p className="mt-4 text-sm text-signal-warn">
                Validation {validation?.status}. {validation?.reason}
              </p>
            )}

            {result?.engine.is_stub && (
              <p className="mt-3 flex items-center gap-2 text-xs text-signal-warn">
                <span className="h-1.5 w-1.5 bg-signal-warn" aria-hidden />
                Produced by the placeholder generator ({result.engine.name}). Not
                releasable output.
              </p>
            )}
          </div>
        </div>
      </div>

      <nav className="flex gap-px border-b border-edge bg-edge">
        {(
          [
            ["summary", "summary"],
            ["screening", "attrition funnel"],
            ["cohort", "cohort rows"],
            ["export", "export"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "border-t-2 bg-surface px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors",
              tab === key
                ? "border-accent text-ink"
                : "border-transparent text-ink-dim hover:text-ink-muted",
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="p-6">
        {tab === "summary" && result && <SummaryTab job={job} />}
        {tab === "screening" && result && <ScreeningTab job={job} />}
        {tab === "cohort" && <CohortTab rows={rows} features={result?.features ?? []} />}
        {tab === "export" && (
          <ExportPanel
            cohortId={jobId}
            rows={rows}
            fidelityScore={fidelity}
            fidelityGrade={validation?.grade}
          />
        )}
      </div>
    </>
  );
}

function SummaryTab({ job }: { job: CohortJob }) {
  const result = job.result;
  if (!result) return null;
  const profile = result.seed_profile;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="panel">
        <div className="panel-header">
          <span className="label-micro">seed</span>
        </div>
        <dl className="divide-y divide-edge-faint">
          <Row label="source" value={profile.source ?? "unknown"} />
          <Row label="rows" value={formatCount(profile.rows)} />
          <Row label="features" value={formatCount(profile.columns)} />
          <Row label="numeric" value={formatCount(profile.numeric_features.length)} />
          <Row label="categorical" value={formatCount(profile.categorical_features.length)} />
          <Row
            label="identifiers stripped"
            value={
              profile.dropped_identifiers.length > 0
                ? profile.dropped_identifiers.join(", ")
                : "none"
            }
          />
        </dl>
      </div>

      <div className="panel">
        <div className="panel-header">
          <span className="label-micro">run</span>
        </div>
        <dl className="divide-y divide-edge-faint">
          <Row label="engine" value={result.engine.name} />
          <Row label="method" value={result.engine.detail} />
          <Row label="storage" value={result.storage.backend} />
          <Row label="duration" value={formatDuration(result.duration_seconds)} />
          <Row
            label="validation"
            value={
              result.validation.status === "complete"
                ? `${formatPercent(result.validation.overall_fidelity)} (${result.validation.grade})`
                : result.validation.status
            }
          />
        </dl>
      </div>
    </div>
  );
}

function ScreeningTab({ job }: { job: CohortJob }) {
  const screening = job.result?.screening;
  if (!screening) return null;

  if (screening.funnel.length === 0) {
    return (
      <div className="panel px-4 py-4 text-sm text-ink-muted">
        No criteria were applied to this cohort, so there is no attrition to report.
      </div>
    );
  }

  const start = screening.funnel[0]?.candidates_in ?? 1;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="label-micro">attrition funnel</span>
        <span className="flex items-center gap-2">
          <span className="label-micro">overall eligibility</span>
          <span className="tabular text-sm text-accent-bright">
            {formatPercent(screening.eligibility_rate * 100, 2)}
          </span>
        </span>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th className="w-8">#</th>
            <th>criterion</th>
            <th className="text-right">in</th>
            <th className="text-right">removed</th>
            <th className="text-right">out</th>
            <th className="w-44">remaining</th>
          </tr>
        </thead>
        <tbody>
          {screening.funnel.map((step, index) => {
            const remaining = (step.candidates_out / start) * 100;
            const heavy = step.removal_rate > 0.4;
            return (
              <tr key={index}>
                <td className="tabular text-xs text-ink-dim">
                  {String(index + 1).padStart(2, "0")}
                </td>
                <td>
                  <span className="font-mono text-[13px] text-ink">{step.criterion}</span>
                  <span
                    className={cn(
                      "ml-2 border px-1.5 py-0.5 font-mono text-[10px] uppercase",
                      step.kind === "inclusion"
                        ? "border-edge text-ink-dim"
                        : "border-signal-fail/50 text-signal-fail",
                    )}
                  >
                    {step.kind === "inclusion" ? "incl" : "excl"}
                  </span>
                  {step.note && (
                    <span className="mt-1 block text-xs text-signal-warn">{step.note}</span>
                  )}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatCount(step.candidates_in)}
                </td>
                <td
                  className={cn(
                    "tabular text-right text-[13px]",
                    heavy ? "text-signal-warn" : "text-ink-muted",
                  )}
                >
                  {step.removed > 0 ? `-${formatCount(step.removed)}` : "0"}
                  <span className="ml-1.5 text-[11px] text-ink-dim">
                    {formatPercent(step.removal_rate * 100, 1)}
                  </span>
                </td>
                <td className="tabular text-right text-[13px] text-ink">
                  {formatCount(step.candidates_out)}
                </td>
                <td>
                  {/* The bar is the funnel. Reading down the column shows
                      where the protocol loses its population. */}
                  <div className="h-2.5 w-full bg-edge-faint">
                    <div
                      className={cn("h-full", heavy ? "bg-signal-warn" : "bg-accent")}
                      style={{ width: `${Math.max(0, Math.min(100, remaining))}%` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {screening.warnings.length > 0 && (
        <ul className="border-t border-edge">
          {screening.warnings.map((warning, index) => (
            <li
              key={index}
              className="flex gap-2.5 border-b border-edge-faint px-4 py-2 text-xs text-ink-muted last:border-b-0"
            >
              <span className="mt-1 h-1 w-1 shrink-0 bg-signal-warn" aria-hidden />
              {warning}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CohortTab({
  rows,
  features,
}: {
  rows: Record<string, unknown>[];
  features: string[];
}) {
  if (rows.length === 0) {
    return (
      <div className="panel px-4 py-4 text-sm text-ink-muted">
        No cohort rows are available. Generated cohorts expire from local storage
        after seven days.
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="label-micro">cohort rows</span>
        <span className="tabular text-xs text-ink-dim">
          showing {formatCount(rows.length)}
        </span>
      </div>
      <div className="max-h-[36rem] overflow-auto">
        <table className="data-table">
          <thead className="sticky top-0 bg-surface-sunken">
            <tr>
              {features.map((feature) => (
                <th key={feature}>{feature}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {features.map((feature) => (
                  <td key={feature} className="tabular text-[12px] text-ink-muted">
                    {formatCell(row[feature])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-sunken px-3.5 py-3">
      <div className="label-micro mb-1.5">{label}</div>
      <div className="tabular text-lg text-ink">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-2.5">
      <dt className="label-micro shrink-0 pt-0.5">{label}</dt>
      <dd className="text-right text-sm text-ink">{value}</dd>
    </div>
  );
}
