"use client";

import { useEffect, useState } from "react";
import { downloadExport } from "@pretrial/fhir-client";
import type { ExportFormat, ExportResult } from "@pretrial/shared-types";

import { ApiRequestError, fhirlink } from "@/lib/api";
import { cn, formatBytes, formatCount, formatPercent, gradeColor } from "@/lib/utils";
import { BundlePreview } from "./BundlePreview";

/**
 * Export gateway panel.
 *
 * The fidelity gate is the load bearing part. FHIR-Link refuses to export a
 * cohort scoring below 70 percent unless the caller explicitly acknowledges
 * it, and that refusal surfaces here as a deliberate second action rather
 * than a checkbox that can be ticked ahead of time. Exporting a cohort that
 * failed its own validation should be possible, because sometimes it is the
 * right call, and it should never be accidental.
 */

export interface ExportPanelProps {
  cohortId: string;
  rows: Record<string, unknown>[];
  fidelityScore?: number;
  fidelityGrade?: string;
  className?: string;
}

export function ExportPanel({
  cohortId,
  rows,
  fidelityScore,
  fidelityGrade,
  className,
}: ExportPanelProps) {
  const [formats, setFormats] = useState<ExportFormat[]>([]);
  const [selected, setSelected] = useState("fhir_r4_collection");
  const [includeObservations, setIncludeObservations] = useState(true);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [preview, setPreview] = useState<{ content: string; isNdjson: boolean } | null>(null);
  const [busy, setBusy] = useState<"idle" | "preview" | "export">("idle");
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fhirlink
      .formats()
      .then((response) => {
        if (!cancelled) setFormats(response.formats);
      })
      .catch(() => {
        if (!cancelled) setError("FHIR-Link could not be reached.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const activeFormat = formats.find((format) => format.id === selected);
  const belowFloor = fidelityScore !== undefined && fidelityScore < 70;

  async function runPreview() {
    setBusy("preview");
    setError(null);
    try {
      const response = await fhirlink.preview({
        rows,
        cohort_id: cohortId,
        format: selected,
        limit: 3,
      });
      setPreview({
        content: response.content,
        isNdjson: response.format.id === "fhir_r4_ndjson",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Preview failed.");
    } finally {
      setBusy("idle");
    }
  }

  async function runExport(acknowledge = false) {
    setBusy("export");
    setError(null);
    try {
      const response = await fhirlink.export({
        rows,
        cohort_id: cohortId,
        format: selected,
        include_observations: includeObservations,
        fidelity_score: fidelityScore,
        acknowledge_low_fidelity: acknowledge,
      });
      setResult(response);
      setBlocked(false);
    } catch (cause) {
      if (cause instanceof ApiRequestError && cause.code === "fidelity_below_export_floor") {
        setBlocked(true);
        setError(cause.message);
      } else {
        setError(cause instanceof Error ? cause.message : "Export failed.");
      }
    } finally {
      setBusy("idle");
    }
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="panel">
        <div className="panel-header">
          <span className="label-micro">export gateway</span>
          {fidelityScore !== undefined && (
            <span className="flex items-center gap-2">
              <span className="label-micro">cohort fidelity</span>
              <span
                className="tabular text-sm"
                style={{ color: gradeColor(fidelityGrade ?? "") }}
              >
                {formatPercent(fidelityScore)}
              </span>
            </span>
          )}
        </div>

        <fieldset className="divide-y divide-edge-faint">
          <legend className="sr-only">Export format</legend>
          {formats.map((format) => (
            <label
              key={format.id}
              className={cn(
                "flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors",
                selected === format.id ? "bg-accent/[0.07]" : "hover:bg-surface-raised/40",
              )}
            >
              <input
                type="radio"
                name="export-format"
                value={format.id}
                checked={selected === format.id}
                onChange={() => {
                  setSelected(format.id);
                  setPreview(null);
                  setResult(null);
                }}
                className="sr-only"
              />
              <span
                className={cn(
                  "mt-1 h-2.5 w-2.5 shrink-0 border",
                  selected === format.id
                    ? "border-accent bg-accent"
                    : "border-edge-strong bg-transparent",
                )}
                aria-hidden
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-ink">{format.label}</span>
                  <span className="border border-edge px-1.5 py-0.5 font-mono text-[10px] text-ink-dim">
                    .{format.extension}
                  </span>
                  {!format.fhir && (
                    <span className="border border-signal-warn px-1.5 py-0.5 font-mono text-[10px] text-signal-warn">
                      no fhir marker
                    </span>
                  )}
                </span>
                <span className="mt-1 block text-xs text-ink-muted">
                  {format.description}
                </span>
              </span>
            </label>
          ))}
        </fieldset>

        {activeFormat?.fhir && (
          <div className="border-t border-edge px-4 py-3">
            <label className="flex cursor-pointer items-center gap-2.5">
              <input
                type="checkbox"
                checked={includeObservations}
                onChange={(event) => setIncludeObservations(event.target.checked)}
                className="sr-only"
              />
              <span
                className={cn(
                  "h-3 w-3 shrink-0 border",
                  includeObservations
                    ? "border-accent bg-accent"
                    : "border-edge-strong bg-transparent",
                )}
                aria-hidden
              />
              <span className="text-sm text-ink">Include Observation resources</span>
            </label>
            <p className="mt-1.5 pl-[22px] text-xs text-ink-dim">
              Off produces a Patient only bundle, which is far smaller and carries
              demographics alone.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-edge bg-surface-sunken p-3">
          <button
            type="button"
            onClick={runPreview}
            disabled={busy !== "idle" || rows.length === 0}
            className="btn btn-secondary"
          >
            {busy === "preview" ? "rendering" : "preview"}
          </button>
          <button
            type="button"
            onClick={() => runExport(false)}
            disabled={busy !== "idle" || rows.length === 0}
            className="btn btn-primary"
          >
            {busy === "export" ? "building" : `export ${formatCount(rows.length)} patients`}
          </button>

          {belowFloor && !blocked && (
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-signal-warn">
              below export floor
            </span>
          )}
        </div>

        {error && (
          <div
            className={cn(
              "border-t px-4 py-3",
              blocked ? "border-signal-warn" : "border-signal-fail",
            )}
          >
            <div
              className={cn(
                "label-micro mb-1.5",
                blocked ? "text-signal-warn" : "text-signal-fail",
              )}
            >
              {blocked ? "export blocked" : "export failed"}
            </div>
            <p className="text-sm text-ink">{error}</p>
            {blocked && (
              <button
                type="button"
                onClick={() => runExport(true)}
                className="btn mt-3 border-signal-warn text-signal-warn hover:bg-signal-warn/10"
              >
                export anyway and record the acknowledgement
              </button>
            )}
          </div>
        )}

        {result && (
          <div className="border-t border-signal-pass bg-signal-pass/[0.05] px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="label-micro mb-1 text-signal-pass">export ready</div>
                <div className="tabular text-sm text-ink">{result.filename}</div>
                <div className="mt-1 flex flex-wrap gap-4 text-xs text-ink-muted">
                  <span>
                    <span className="tabular text-ink">
                      {formatCount(result.bundle.patients)}
                    </span>{" "}
                    patients
                  </span>
                  <span>
                    <span className="tabular text-ink">
                      {formatCount(result.bundle.observations)}
                    </span>{" "}
                    observations
                  </span>
                  <span>
                    <span className="tabular text-ink">
                      {formatBytes(result.size_bytes)}
                    </span>
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() =>
                  downloadExport(result.content, result.filename, {
                    media_type: result.media_type,
                  })
                }
                className="btn btn-primary"
              >
                download
              </button>
            </div>

            {result.bundle.unmapped_features.length > 0 && (
              <div className="mt-3 border-t border-edge pt-3">
                <div className="label-micro mb-1.5 text-signal-warn">
                  exported under the local code system
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {result.bundle.unmapped_features.map((feature) => (
                    <span
                      key={feature}
                      className="border border-edge-strong px-2 py-0.5 font-mono text-[11px] text-ink-muted"
                    >
                      {feature}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-xs text-ink-dim">
                  No LOINC mapping is configured for these features. A receiving
                  system will not recognise the codes without a local mapping.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {preview && (
        <BundlePreview
          content={preview.content}
          isNdjson={preview.isNdjson}
          patientsInPreview={Math.min(3, rows.length)}
          patientsTotal={rows.length}
        />
      )}
    </div>
  );
}
