"use client";

import { useMemo, useState } from "react";
import {
  countResources,
  isMarkedSynthetic,
  parseBundle,
  parseNdjson,
  unmarkedResources,
  type FhirBundle,
} from "@pretrial/fhir-client";

import { cn, formatBytes, formatCount } from "@/lib/utils";

/**
 * Renders an export before it leaves the building.
 *
 * The compliance strip at the top is the point of this component. It
 * independently re-checks, in the browser, that every resource carries the
 * HTEST synthetic data marker. The service already guarantees this. It is
 * checked again here because an untagged synthetic patient record landing in
 * a hospital warehouse is the worst thing this product can do, and one
 * verification is not enough for that failure mode.
 */

const MAX_RENDERED_CHARS = 200_000;

export interface BundlePreviewProps {
  content: string;
  /** NDJSON is resource per line, so it parses differently from a bundle. */
  isNdjson?: boolean;
  patientsInPreview?: number;
  patientsTotal?: number;
  className?: string;
}

export function BundlePreview({
  content,
  isNdjson = false,
  patientsInPreview,
  patientsTotal,
  className,
}: BundlePreviewProps) {
  const [view, setView] = useState<"summary" | "raw">("summary");

  const parsed = useMemo(() => {
    try {
      if (isNdjson) {
        const resources = parseNdjson(content);
        const asBundle: FhirBundle = {
          resourceType: "Bundle",
          type: "collection",
          entry: resources.map((resource) => ({ resource })),
        };
        return { bundle: asBundle, error: null as string | null };
      }
      return { bundle: parseBundle(content), error: null as string | null };
    } catch (cause) {
      return {
        bundle: null,
        error: cause instanceof Error ? cause.message : "Could not parse the export.",
      };
    }
  }, [content, isNdjson]);

  if (parsed.error || !parsed.bundle) {
    return (
      <div className={cn("panel px-4 py-4", className)}>
        <div className="label-micro mb-1.5 text-signal-fail">unparseable export</div>
        <p className="text-sm text-ink-muted">{parsed.error}</p>
      </div>
    );
  }

  const bundle = parsed.bundle;
  const counts = countResources(bundle);
  const marked = isMarkedSynthetic(bundle);
  const unmarked = marked ? [] : unmarkedResources(bundle);
  const truncated = content.length > MAX_RENDERED_CHARS;

  return (
    <div className={cn("panel", className)}>
      <div className="panel-header">
        <span className="label-micro">bundle preview</span>
        <div className="flex items-center gap-1">
          {(["summary", "raw"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setView(mode)}
              className={cn(
                "border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
                view === mode
                  ? "border-accent text-accent-bright"
                  : "border-transparent text-ink-dim hover:text-ink-muted",
              )}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Compliance strip. Full width, colour coded, above everything else. */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-3 border-b px-4 py-2",
          marked
            ? "border-edge bg-signal-pass/[0.06]"
            : "border-signal-fail bg-signal-fail/10",
        )}
      >
        <span
          className={cn("h-1.5 w-1.5", marked ? "bg-signal-pass" : "bg-signal-fail")}
          aria-hidden
        />
        <span
          className={cn(
            "font-mono text-[10px] uppercase tracking-[0.12em]",
            marked ? "text-signal-pass" : "text-signal-fail",
          )}
        >
          {marked ? "HTEST marker present on every resource" : "synthetic marker missing"}
        </span>
        <span className="text-[11px] text-ink-dim">
          {marked
            ? "Receiving systems will read these resources as test health data."
            : `Unmarked: ${unmarked.slice(0, 3).join(", ")}`}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-px bg-edge sm:grid-cols-4">
        <Cell label="bundle type" value={bundle.type} />
        <Cell label="entries" value={formatCount(bundle.entry?.length ?? 0)} />
        <Cell
          label="patients"
          value={
            patientsTotal !== undefined && patientsInPreview !== undefined
              ? `${formatCount(patientsInPreview)} of ${formatCount(patientsTotal)}`
              : formatCount(counts.Patient ?? 0)
          }
        />
        <Cell label="size" value={formatBytes(new Blob([content]).size)} />
      </div>

      {view === "summary" ? (
        <div className="p-4">
          <div className="label-micro mb-2.5">resources by type</div>
          <div className="space-y-1.5">
            {Object.entries(counts)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => {
                const total = bundle.entry?.length ?? 1;
                return (
                  <div key={type} className="flex items-center gap-3">
                    <span className="w-28 shrink-0 font-mono text-xs text-ink">{type}</span>
                    <div className="h-2.5 flex-1 bg-edge-faint">
                      <div
                        className="h-full bg-accent"
                        style={{ width: `${(count / total) * 100}%` }}
                      />
                    </div>
                    <span className="tabular w-14 shrink-0 text-right text-xs text-ink-muted">
                      {formatCount(count)}
                    </span>
                  </div>
                );
              })}
          </div>

          <div className="mt-5">
            <div className="label-micro mb-2">first resource</div>
            <pre className="max-h-72 overflow-auto border border-edge bg-surface-sunken p-3 font-mono text-[11px] leading-relaxed text-ink-muted">
              {JSON.stringify(bundle.entry?.[0]?.resource ?? {}, null, 2)}
            </pre>
          </div>
        </div>
      ) : (
        <div className="p-3">
          <pre className="max-h-[32rem] overflow-auto border border-edge bg-surface-sunken p-3 font-mono text-[11px] leading-relaxed text-ink-muted">
            {truncated ? `${content.slice(0, MAX_RENDERED_CHARS)}\n\n...` : content}
          </pre>
          {truncated && (
            <p className="mt-2 text-xs text-ink-dim">
              Preview truncated at {formatCount(MAX_RENDERED_CHARS)} characters. The
              downloaded file is complete.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-3.5 py-3">
      <div className="label-micro mb-1.5">{label}</div>
      <div className="tabular truncate text-sm text-ink">{value}</div>
    </div>
  );
}
