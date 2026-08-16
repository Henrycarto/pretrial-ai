"use client";

import { useState } from "react";
import type { FidelityReport, FeatureFidelity } from "@pretrial/shared-types";

import { DistributionChartGrid } from "./DistributionChart";
import { FidelityScoreBadge, FidelityScoreInline } from "./FidelityScoreBadge";
import {
  cn,
  formatCount,
  formatPercent,
  formatPValue,
  formatStatistic,
  gradeColor,
} from "@/lib/utils";

/**
 * The full validation report.
 *
 * Reading order is deliberate and matches how the decision actually gets
 * made: the score, then the verdict sentence, then the three components that
 * produced the score, then the per feature table, then the charts, then the
 * correlation detail. A director stops after the first two. A biostatistician
 * reads to the bottom. Neither has to scroll past the other's material to
 * find their own.
 */

export interface ValidationReportProps {
  report: FidelityReport;
  className?: string;
}

export function ValidationReport({ report, className }: ValidationReportProps) {
  return (
    <div className={cn("flex flex-col gap-px bg-edge", className)}>
      <ReportHeadline report={report} />
      {report.warnings.length > 0 && <WarningPanel warnings={report.warnings} />}
      <ComponentBreakdown report={report} />
      <FeatureTable features={report.features} />
      <section className="bg-shell pt-px">
        <div className="panel-header">
          <span className="label-micro">
            distribution comparison, real against synthetic
          </span>
          <span className="label-micro">
            {report.distribution_preview_ranking.replace(/_/g, " ")}
          </span>
        </div>
        <DistributionChartGrid previews={report.distribution_previews} />
      </section>
      <CorrelationPanel report={report} />
    </div>
  );
}

function ReportHeadline({ report }: { report: FidelityReport }) {
  const color = gradeColor(report.grade);
  const coveragePenalty = report.raw_fidelity - report.overall_fidelity;

  return (
    <section className="bg-surface">
      <div className="flex flex-col gap-8 px-6 py-7 lg:flex-row lg:items-center">
        <FidelityScoreBadge
          score={report.overall_fidelity}
          grade={report.grade}
          size="lg"
        />

        <div className="min-w-0 flex-1">
          <div className="label-micro mb-2">validation verdict</div>
          <p className="max-w-2xl text-[15px] leading-relaxed text-ink">
            {report.verdict}
          </p>

          <div className="mt-6 grid grid-cols-2 gap-px border border-edge bg-edge sm:grid-cols-4">
            <Stat label="reference rows" value={formatCount(report.row_counts.real)} />
            <Stat label="synthetic rows" value={formatCount(report.row_counts.synthetic)} />
            <Stat label="features compared" value={formatCount(report.features.length)} />
            <Stat
              label="schema coverage"
              value={formatPercent(report.components.schema_coverage)}
              tone={report.components.schema_coverage < 100 ? "warn" : "neutral"}
            />
          </div>

          {coveragePenalty > 0.05 && (
            <p className="mt-3 text-xs text-ink-muted">
              Statistical agreement alone scores{" "}
              <span className="tabular text-ink">
                {formatPercent(report.raw_fidelity)}
              </span>
              . The reported figure applies the schema coverage multiplier, costing{" "}
              <span className="tabular" style={{ color: "#F59E0B" }}>
                {formatPercent(coveragePenalty)}
              </span>{" "}
              because the synthetic cohort does not carry every requested feature.
            </p>
          )}
        </div>
      </div>

      <div className="h-px w-full" style={{ backgroundColor: color }} />
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warn";
}) {
  return (
    <div className="bg-surface-sunken px-3.5 py-3">
      <div className="label-micro mb-1.5">{label}</div>
      <div
        className={cn("tabular text-lg", tone === "warn" ? "text-signal-warn" : "text-ink")}
      >
        {value}
      </div>
    </div>
  );
}

function WarningPanel({ warnings }: { warnings: string[] }) {
  return (
    <section className="bg-surface">
      <div className="panel-header">
        <span className="label-micro">notices</span>
        <span className="tabular text-xs text-signal-warn">{warnings.length}</span>
      </div>
      <ul className="divide-y divide-edge-faint">
        {warnings.map((warning, index) => (
          <li key={index} className="flex gap-3 px-4 py-2.5 text-sm text-ink-muted">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 bg-signal-warn" aria-hidden />
            <span>{warning}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ComponentBreakdown({ report }: { report: FidelityReport }) {
  const components = [
    {
      key: "marginal_agreement",
      label: "marginal agreement",
      test: "Kolmogorov-Smirnov / total variation",
      value: report.components.marginal_agreement,
      weight: report.weights.marginal_agreement,
    },
    {
      key: "shape_agreement",
      label: "shape agreement",
      test: "Jensen-Shannon divergence",
      value: report.components.shape_agreement,
      weight: report.weights.shape_agreement,
    },
    {
      key: "dependency_structure",
      label: "dependency structure",
      test: `${report.correlation.method} correlation matrix delta`,
      value: report.components.dependency_structure,
      weight: report.weights.dependency_structure,
    },
  ];

  return (
    <section className="bg-surface">
      <div className="panel-header">
        <span className="label-micro">score composition</span>
        <span className="label-micro">weighted, renormalised over evaluated components</span>
      </div>
      <div className="grid grid-cols-1 gap-px bg-edge sm:grid-cols-3">
        {components.map((component) => {
          const value = component.value;
          const has = typeof value === "number";
          const color = has ? gradeColor(gradeFor(value)) : "#62789A";
          return (
            <div key={component.key} className="bg-surface px-4 py-4">
              <div className="flex items-baseline justify-between">
                <span className="label-micro">{component.label}</span>
                <span className="tabular text-[10px] text-ink-dim">
                  w {component.weight?.toFixed(2)}
                </span>
              </div>
              <div className="tabular mt-2 text-2xl" style={{ color }}>
                {has ? formatPercent(value) : "n/a"}
              </div>
              {/* A bar rather than another ring. Three rings next to the
                  signature badge would compete with it. */}
              <div className="mt-3 h-1 w-full bg-edge">
                <div
                  className="h-full"
                  style={{
                    width: `${has ? Math.max(0, Math.min(100, value)) : 0}%`,
                    backgroundColor: color,
                  }}
                />
              </div>
              <div className="mt-2.5 text-xs text-ink-dim">{component.test}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

type SortKey = "feature" | "fidelity" | "ks" | "js";

function FeatureTable({ features }: { features: FeatureFidelity[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("fidelity");

  const sorted = [...features].sort((a, b) => {
    switch (sortKey) {
      case "feature":
        return a.feature.localeCompare(b.feature);
      case "ks":
        return (b.ks_statistic ?? -1) - (a.ks_statistic ?? -1);
      case "js":
        return (b.js_divergence ?? -1) - (a.js_divergence ?? -1);
      default:
        // Worst first. The reviewer is looking for what failed, not what
        // passed, so the default sort puts the problem at the top.
        return a.fidelity - b.fidelity;
    }
  });

  return (
    <section className="bg-surface">
      <div className="panel-header">
        <span className="label-micro">per feature results</span>
        <div className="flex items-center gap-1">
          {(
            [
              ["fidelity", "fidelity"],
              ["ks", "ks d"],
              ["js", "js div"],
              ["feature", "name"],
            ] as [SortKey, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSortKey(key)}
              className={cn(
                "border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
                sortKey === key
                  ? "border-accent text-accent-bright"
                  : "border-transparent text-ink-dim hover:text-ink-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>feature</th>
              <th>type</th>
              <th className="text-right">fidelity</th>
              <th className="text-right">ks d</th>
              <th className="text-right">p value</th>
              <th className="text-right">js divergence</th>
              <th className="text-right">n real</th>
              <th className="text-right">n synthetic</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((feature) => (
              <tr key={feature.feature}>
                <td className="font-mono text-[13px] text-ink">{feature.feature}</td>
                <td className="text-xs text-ink-dim">{feature.kind}</td>
                <td className="text-right">
                  {feature.evaluated ? (
                    <FidelityScoreInline score={feature.fidelity} className="justify-end" />
                  ) : (
                    <span className="text-xs text-ink-dim">not evaluated</span>
                  )}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatStatistic(feature.ks_statistic)}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatPValue(feature.ks_p_value)}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatStatistic(feature.js_divergence)}
                </td>
                <td className="tabular text-right text-[13px] text-ink-dim">
                  {formatCount(feature.n_real)}
                </td>
                <td className="tabular text-right text-[13px] text-ink-dim">
                  {formatCount(feature.n_synthetic)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="border-t border-edge px-4 py-2.5 text-xs text-ink-dim">
        The p value is reported for completeness. The score is derived from the KS
        statistic rather than from significance, because at cohort scale a KS test
        rejects the null on differences too small to affect feasibility.
      </p>
    </section>
  );
}

function CorrelationPanel({ report }: { report: FidelityReport }) {
  const correlation = report.correlation;

  if (!correlation.evaluated) {
    return (
      <section className="bg-surface px-4 py-4">
        <div className="label-micro mb-2">dependency structure</div>
        <p className="text-sm text-ink-muted">
          {correlation.note ?? "Correlation comparison was not evaluated."}
        </p>
      </section>
    );
  }

  return (
    <section className="bg-surface">
      <div className="panel-header">
        <span className="label-micro">dependency structure, largest deltas</span>
        <div className="flex items-center gap-4">
          <MetaFigure label="rms delta" value={formatStatistic(correlation.rms_delta)} />
          <MetaFigure label="max abs delta" value={formatStatistic(correlation.max_absolute_delta)} />
          <MetaFigure label="mean abs delta" value={formatStatistic(correlation.mean_absolute_delta)} />
          <MetaFigure label="pairs" value={formatCount(correlation.pairs_compared)} />
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>feature pair</th>
            <th className="text-right">real r</th>
            <th className="text-right">synthetic r</th>
            <th className="text-right">delta</th>
          </tr>
        </thead>
        <tbody>
          {correlation.worst_pairs.map((pair) => {
            const severity = Math.abs(pair.delta);
            const color =
              severity > 0.3 ? "#EF4444" : severity > 0.15 ? "#F59E0B" : "#8FA4C0";
            return (
              <tr key={`${pair.feature_a}:${pair.feature_b}`}>
                <td className="font-mono text-[13px] text-ink">
                  {pair.feature_a}
                  <span className="px-1.5 text-ink-dim">x</span>
                  {pair.feature_b}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatStatistic(pair.real, 3)}
                </td>
                <td className="tabular text-right text-[13px] text-ink-muted">
                  {formatStatistic(pair.synthetic, 3)}
                </td>
                <td className="tabular text-right text-[13px]" style={{ color }}>
                  {pair.delta > 0 ? "+" : ""}
                  {formatStatistic(pair.delta, 3)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="border-t border-edge px-4 py-2.5 text-xs text-ink-dim">
        A large delta here with high per feature scores above means the generator
        reproduced each variable on its own and lost the relationship between them.
        That pattern passes screening and fails at analysis. The score is built
        from the RMS and worst case deltas rather than the mean, because a mean
        taken across every feature pair hides a single destroyed relationship.
      </p>
    </section>
  );
}

function MetaFigure({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="label-micro">{label}</span>
      <span className="tabular text-xs text-ink">{value}</span>
    </span>
  );
}

function gradeFor(score: number): "pass" | "borderline" | "fail" {
  if (score >= 90) return "pass";
  if (score >= 70) return "borderline";
  return "fail";
}
