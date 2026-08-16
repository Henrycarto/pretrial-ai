"use client";

import { useRef, useState } from "react";
import type { SeedProfile } from "@pretrial/shared-types";

import { synthecore } from "@/lib/api";
import { cn, formatCount, formatPercent } from "@/lib/utils";

/**
 * Seed cohort upload.
 *
 * The panel reports what the service stripped as loudly as what it kept.
 * Direct identifiers are removed server side before the generator ever sees
 * the frame, and an operator who uploaded a file containing an MRN column
 * needs to know that happened, both because it is reassuring and because it
 * tells them their extract was wider than it should have been.
 *
 * Rows never come back to the browser. The response carries the object key
 * and the profile, which is everything the cohort builder needs.
 */

const ACCEPTED = ".csv,.tsv,.json,.ndjson,.parquet";

export interface SeedDataUploaderProps {
  onUploaded: (seedObjectKey: string, profile: SeedProfile) => void;
  onCleared?: () => void;
  className?: string;
}

export function SeedDataUploader({
  onUploaded,
  onCleared,
  className,
}: SeedDataUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [profile, setProfile] = useState<SeedProfile | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function handleFile(file: File) {
    setState("uploading");
    setError(null);
    setFilename(file.name);

    try {
      const result = await synthecore.uploadSeed(file);
      setProfile(result.profile);
      setState("done");
      onUploaded(result.seed_object_key, result.profile);
    } catch (cause) {
      setState("error");
      setError(cause instanceof Error ? cause.message : "Upload failed.");
    }
  }

  function clear() {
    setState("idle");
    setProfile(null);
    setFilename(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
    onCleared?.();
  }

  return (
    <div className={cn("panel", className)}>
      <div className="panel-header">
        <span className="label-micro">seed cohort</span>
        {state === "done" && (
          <button type="button" onClick={clear} className="btn btn-ghost !px-2 !py-0.5">
            clear
          </button>
        )}
      </div>

      {state !== "done" && (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const file = event.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          className={cn(
            "m-3 border border-dashed px-4 py-8 text-center transition-colors",
            dragging ? "border-accent bg-accent/5" : "border-edge-strong",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED}
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />

          {state === "uploading" ? (
            <div className="label-micro text-accent-bright">
              parsing {filename}
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="btn btn-secondary"
              >
                select seed file
              </button>
              <p className="mt-3 text-xs text-ink-dim">
                CSV, TSV, JSON, NDJSON, or Parquet. Drag a file here to upload.
              </p>
              <p className="mt-1.5 text-xs text-ink-dim">
                Leave empty to generate against the built in reference population.
              </p>
            </>
          )}
        </div>
      )}

      {state === "error" && error && (
        <div className="border-t border-signal-fail px-4 py-3">
          <div className="label-micro mb-1 text-signal-fail">upload rejected</div>
          <p className="text-sm text-ink">{error}</p>
        </div>
      )}

      {state === "done" && profile && (
        <SeedProfileSummary profile={profile} filename={filename} />
      )}
    </div>
  );
}

function SeedProfileSummary({
  profile,
  filename,
}: {
  profile: SeedProfile;
  filename: string | null;
}) {
  const stripped = [...profile.dropped_identifiers, ...profile.dropped_free_text];

  return (
    <div>
      <div className="grid grid-cols-2 gap-px bg-edge sm:grid-cols-4">
        <Cell label="file" value={filename ?? "seed"} mono={false} />
        <Cell label="rows" value={formatCount(profile.rows)} />
        <Cell label="features" value={formatCount(profile.columns)} />
        <Cell
          label="numeric / categorical"
          value={`${profile.numeric_features.length} / ${profile.categorical_features.length}`}
        />
      </div>

      {stripped.length > 0 && (
        <div className="border-t border-edge px-4 py-3">
          <div className="label-micro mb-2 text-signal-warn">
            removed before modelling
          </div>
          <div className="flex flex-wrap gap-1.5">
            {stripped.map((column) => (
              <span
                key={column}
                className="border border-edge-strong px-2 py-0.5 font-mono text-[11px] text-ink-muted line-through"
              >
                {column}
              </span>
            ))}
          </div>
          <p className="mt-2 text-xs text-ink-dim">
            Direct identifiers and free text are stripped server side. The generator
            never receives them.
          </p>
        </div>
      )}

      <div className="border-t border-edge px-4 py-3">
        <div className="label-micro mb-2">features retained</div>
        <div className="flex flex-wrap gap-1.5">
          {profile.feature_names.map((feature) => {
            const nullRate = profile.null_rates[feature] ?? 0;
            return (
              <span
                key={feature}
                className="flex items-center gap-1.5 border border-edge px-2 py-0.5 font-mono text-[11px] text-ink"
                title={`${formatPercent(nullRate * 100)} null`}
              >
                {feature}
                {nullRate > 0.05 && (
                  <span className="tabular text-[10px] text-signal-warn">
                    {formatPercent(nullRate * 100, 0)}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>

      {profile.warnings.length > 0 && (
        <ul className="border-t border-edge">
          {profile.warnings.map((warning, index) => (
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

function Cell({
  label,
  value,
  mono = true,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-surface px-3.5 py-3">
      <div className="label-micro mb-1.5">{label}</div>
      <div className={cn("truncate text-sm text-ink", mono && "tabular")} title={value}>
        {value}
      </div>
    </div>
  );
}
