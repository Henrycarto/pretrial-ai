"use client";

import { gradeForScore, type FidelityGrade } from "@pretrial/shared-types";

import { cn, formatPercent, gradeColor } from "@/lib/utils";

/**
 * The signature element of the product.
 *
 * A pharma clinical operations director looks at exactly one number to
 * decide whether a cohort is usable, and this is it. Everything about the
 * component serves reading that number quickly and correctly:
 *
 *   The figure is JetBrains Mono at 48px in the default size. Mono on the
 *   score is the whole point. It says the value was computed, not chosen.
 *
 *   The ring is a progress arc, not decoration. Its sweep is the score and
 *   its colour is the grade, so the badge is readable at a glance from
 *   across a room and still exact up close.
 *
 *   Thresholds come from FIDELITY_THRESHOLDS in @pretrial/shared-types,
 *   which mirrors PASS_THRESHOLD and BORDERLINE_THRESHOLD in
 *   report_builder.py. The two must move together. A green ring on a cohort
 *   the service graded as failing is the worst bug this component can have.
 */

type BadgeSize = "sm" | "md" | "lg";

interface SizeSpec {
  box: number;
  stroke: number;
  fontSize: string;
  labelClass: string;
}

const SIZES: Record<BadgeSize, SizeSpec> = {
  sm: { box: 76, stroke: 4, fontSize: "18px", labelClass: "text-[8px]" },
  md: { box: 124, stroke: 6, fontSize: "30px", labelClass: "text-[9px]" },
  lg: { box: 184, stroke: 8, fontSize: "48px", labelClass: "text-micro" },
};

const GRADE_TEXT: Record<FidelityGrade, string> = {
  pass: "Validated",
  borderline: "Borderline",
  fail: "Failed",
};

export interface FidelityScoreBadgeProps {
  /** Overall fidelity, 0 to 100. */
  score: number | null | undefined;
  size?: BadgeSize;
  /** Overrides the grade derived from the score. Pass the service's grade. */
  grade?: FidelityGrade;
  showLabel?: boolean;
  className?: string;
}

export function FidelityScoreBadge({
  score,
  size = "lg",
  grade,
  showLabel = true,
  className,
}: FidelityScoreBadgeProps) {
  const spec = SIZES[size];
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const value = hasScore ? Math.max(0, Math.min(100, score)) : 0;

  // Trust the service's grade when it sends one. Deriving it locally is the
  // fallback for cohorts recorded before the grade was part of the payload.
  const resolvedGrade: FidelityGrade = grade ?? gradeForScore(value);
  const color = hasScore ? gradeColor(resolvedGrade) : "#62789A";

  const radius = (spec.box - spec.stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (value / 100) * circumference;

  return (
    <div className={cn("inline-flex flex-col items-center gap-2", className)}>
      <div className="relative" style={{ width: spec.box, height: spec.box }}>
        <svg
          width={spec.box}
          height={spec.box}
          viewBox={`0 0 ${spec.box} ${spec.box}`}
          role="img"
          aria-label={
            hasScore
              ? `Fidelity score ${value.toFixed(1)} percent, graded ${resolvedGrade}`
              : "Fidelity score not available"
          }
        >
          {/* Track. The full circle, so the unfilled portion reads as the
              remaining distance to 100 rather than as empty space. */}
          <circle
            cx={spec.box / 2}
            cy={spec.box / 2}
            r={radius}
            fill="none"
            stroke="#1C3049"
            strokeWidth={spec.stroke}
          />
          {hasScore && (
            <circle
              cx={spec.box / 2}
              cy={spec.box / 2}
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth={spec.stroke}
              strokeDasharray={`${filled} ${circumference - filled}`}
              // Start the sweep at twelve o'clock and run clockwise, which is
              // how a gauge is read.
              transform={`rotate(-90 ${spec.box / 2} ${spec.box / 2})`}
              strokeLinecap="butt"
            />
          )}
          {/* Threshold ticks at 70 and 90. They put the number in context
              without a legend: a director can see how far the arc sits from
              the pass mark. */}
          {[70, 90].map((threshold) => {
            const angle = (threshold / 100) * 2 * Math.PI - Math.PI / 2;
            const inner = radius - spec.stroke / 2 - 1;
            const outer = radius + spec.stroke / 2 + 1;
            const cx = spec.box / 2;
            const cy = spec.box / 2;
            return (
              <line
                key={threshold}
                x1={cx + Math.cos(angle) * inner}
                y1={cy + Math.sin(angle) * inner}
                x2={cx + Math.cos(angle) * outer}
                y2={cy + Math.sin(angle) * outer}
                stroke="#27415F"
                strokeWidth={1}
              />
            );
          })}
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="tabular font-medium leading-none"
            style={{ fontSize: spec.fontSize, color }}
          >
            {hasScore ? value.toFixed(1) : "--"}
            <span
              className="tabular"
              style={{ fontSize: `calc(${spec.fontSize} * 0.42)`, color }}
            >
              %
            </span>
          </span>
          {size !== "sm" && (
            <span className={cn("label-micro mt-1.5", spec.labelClass)}>fidelity</span>
          )}
        </div>
      </div>

      {showLabel && (
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block h-1.5 w-1.5"
            style={{ backgroundColor: color }}
            aria-hidden
          />
          <span
            className="font-mono text-micro uppercase tracking-[0.14em]"
            style={{ color }}
          >
            {hasScore ? GRADE_TEXT[resolvedGrade] : "Not scored"}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Inline variant for table rows and list items, where a ring would be noise.
 * Same colour rules, same mono figure, no arc.
 */
export function FidelityScoreInline({
  score,
  grade,
  className,
}: {
  score: number | null | undefined;
  grade?: FidelityGrade;
  className?: string;
}) {
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const resolved: FidelityGrade = grade ?? gradeForScore(hasScore ? score : 0);
  const color = hasScore ? gradeColor(resolved) : "#62789A";

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="h-3 w-0.5" style={{ backgroundColor: color }} aria-hidden />
      <span className="tabular text-sm" style={{ color }}>
        {hasScore ? formatPercent(score) : "n/a"}
      </span>
    </span>
  );
}
