"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DistributionPreview } from "@pretrial/shared-types";

import { cn, formatPercent, formatStatistic, gradeColor } from "@/lib/utils";
import { gradeForScore } from "@pretrial/shared-types";

/**
 * Real against synthetic, one feature, bars side by side.
 *
 * Two decisions worth stating.
 *
 * Grouped bars rather than overlaid translucent areas. Overlay reads well
 * for two smooth curves and badly for the binned, sometimes spiky
 * distributions that clinical features actually produce, because the eye
 * cannot recover the smaller value where they overlap. Side by side bars
 * make every bin directly comparable, which is what the reviewer is here
 * to do.
 *
 * Density on the y axis, not counts. The two cohorts are almost never the
 * same size, and plotting raw counts makes a faithful synthetic cohort of a
 * different size look wrong.
 *
 * The bins come from FidelityCheck, which computed them once over the pooled
 * sample. The chart does not re-bin, so what is drawn is exactly what the
 * divergence was computed on.
 */

const REAL_COLOR = "#62789A";
const SYNTHETIC_COLOR = "#2563EB";

interface ChartRow {
  bin: string;
  real: number;
  synthetic: number;
}

export interface DistributionChartProps {
  preview: DistributionPreview;
  height?: number;
  className?: string;
}

export function DistributionChart({
  preview,
  height = 200,
  className,
}: DistributionChartProps) {
  const rows: ChartRow[] = preview.bins.map((bin, index) => ({
    bin,
    real: (preview.real[index] ?? 0) * 100,
    synthetic: (preview.synthetic[index] ?? 0) * 100,
  }));

  const grade = gradeForScore(preview.fidelity);
  const accent = gradeColor(grade);

  return (
    <div className={cn("panel", className)}>
      <div className="panel-header">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-sm text-ink">{preview.feature}</span>
          <span className="label-micro">{preview.kind}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="label-micro">fidelity</span>
          <span className="tabular text-sm" style={{ color: accent }}>
            {formatPercent(preview.fidelity)}
          </span>
        </div>
      </div>

      <div className="px-2 pb-2 pt-4">
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={rows} margin={{ top: 4, right: 12, bottom: 4, left: 0 }} barGap={1}>
            <CartesianGrid strokeDasharray="0" vertical={false} stroke="#152438" />
            <XAxis
              dataKey="bin"
              tickLine={false}
              axisLine={{ stroke: "#1C3049" }}
              interval="preserveStartEnd"
              // Bin labels are ranges like "62.4 to 68.1". Angling them keeps
              // the axis readable without truncating to something ambiguous.
              angle={-30}
              textAnchor="end"
              height={48}
            />
            <YAxis
              tickLine={false}
              axisLine={{ stroke: "#1C3049" }}
              width={44}
              tickFormatter={(value: number) => `${value.toFixed(0)}%`}
            />
            <Tooltip
              cursor={{ fill: "rgba(37, 99, 235, 0.08)" }}
              content={<DistributionTooltip />}
            />
            <Legend
              verticalAlign="top"
              align="right"
              height={24}
              iconType="square"
              iconSize={8}
              formatter={(value) => (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">
                  {value}
                </span>
              )}
            />
            <Bar dataKey="real" name="real" fill={REAL_COLOR} isAnimationActive={false} />
            <Bar
              dataKey="synthetic"
              name="synthetic"
              fill={SYNTHETIC_COLOR}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface TooltipPayloadEntry {
  name?: string;
  value?: number;
  color?: string;
}

function DistributionTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const real = payload.find((entry) => entry.name === "real")?.value ?? 0;
  const synthetic = payload.find((entry) => entry.name === "synthetic")?.value ?? 0;
  const delta = synthetic - real;

  return (
    <div className="border border-edge-strong bg-surface-sunken px-3 py-2">
      <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-dim">
        {label}
      </div>
      <TooltipRow color={REAL_COLOR} name="real" value={real} />
      <TooltipRow color={SYNTHETIC_COLOR} name="synthetic" value={synthetic} />
      <div className="mt-1.5 border-t border-edge pt-1.5">
        <TooltipRow
          color={Math.abs(delta) > 2 ? "#F59E0B" : "#62789A"}
          name="delta"
          value={delta}
          signed
        />
      </div>
    </div>
  );
}

function TooltipRow({
  color,
  name,
  value,
  signed = false,
}: {
  color: string;
  name: string;
  value: number;
  signed?: boolean;
}) {
  const sign = signed && value > 0 ? "+" : "";
  return (
    <div className="flex items-center justify-between gap-6 text-xs">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-2" style={{ backgroundColor: color }} />
        <span className="text-ink-muted">{name}</span>
      </span>
      <span className="tabular" style={{ color }}>
        {sign}
        {formatStatistic(value, 2)}%
      </span>
    </div>
  );
}

/**
 * The grid the validation report renders. Worst scoring features first,
 * because those are the ones that decide whether the cohort is usable.
 */
export function DistributionChartGrid({
  previews,
  className,
}: {
  previews: DistributionPreview[];
  className?: string;
}) {
  if (previews.length === 0) {
    return (
      <div className={cn("panel px-4 py-6 text-sm text-ink-muted", className)}>
        No distribution comparisons were produced for this cohort.
      </div>
    );
  }

  return (
    <div className={cn("grid grid-cols-1 gap-px bg-edge xl:grid-cols-2", className)}>
      {previews.map((preview) => (
        <DistributionChart key={preview.feature} preview={preview} />
      ))}
    </div>
  );
}
