import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Number formatting helpers.
 *
 * Every one of these returns a string destined for a `.tabular` element.
 * Precision is fixed per kind rather than chosen per call site, so the same
 * quantity does not appear as 0.043 in one panel and 0.04 in the next.
 */

/** Percentages carry one decimal. 94.7, not 95 and not 94.73. */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${value.toFixed(digits)}%`;
}

/** Test statistics carry four decimals. Below that a small D reads as zero. */
export function formatStatistic(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

/**
 * p-values below 0.0001 are shown as an inequality rather than as a run of
 * zeroes. A reviewer reads "< 0.0001" instantly and "0.0000" as a rounding
 * bug.
 */
export function formatPValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  if (value < 0.0001) return "< 0.0001";
  return value.toFixed(4);
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "n/a";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder.toString().padStart(2, "0")}s`;
}

export function formatTimestamp(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "n/a";
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 19);
}

/** Colour token for a fidelity grade. Used by badges, rules, and chart marks. */
export function gradeColor(grade: string): string {
  switch (grade) {
    case "pass":
      return "#10B981";
    case "borderline":
      return "#F59E0B";
    case "fail":
      return "#EF4444";
    default:
      return "#62789A";
  }
}
