"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Criterion, SeedProfile } from "@pretrial/shared-types";

import { synthecore, ApiRequestError } from "@/lib/api";
import { cn, formatCount } from "@/lib/utils";
import { CriteriaConfigurator } from "./CriteriaConfigurator";
import { GenerationProgress } from "./GenerationProgress";
import { SeedDataUploader } from "./SeedDataUploader";

/**
 * The cohort generation form.
 *
 * Once a job is queued the form is replaced by the live pipeline view rather
 * than sitting behind a modal. The job is the thing the operator now cares
 * about, and generation takes minutes, so it gets the whole surface.
 */

// Features offered when no seed file is uploaded. These are the columns the
// built in reference population carries, so the criteria builder is usable
// on a demo run without a file.
const REFERENCE_FEATURES = [
  "age",
  "sex",
  "bmi",
  "egfr",
  "hba1c",
  "systolic_bp",
  "on_insulin",
  "ecog_status",
  "prior_cv_event",
];

const SIZE_PRESETS = [1000, 5000, 25000, 100000];

export function CohortBuilder({ className }: { className?: string }) {
  const router = useRouter();

  const [trialName, setTrialName] = useState("");
  const [cohortSize, setCohortSize] = useState(5000);
  const [seedKey, setSeedKey] = useState<string | null>(null);
  const [seedProfile, setSeedProfile] = useState<SeedProfile | null>(null);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const features = seedProfile?.feature_names ?? REFERENCE_FEATURES;

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const job = await synthecore.generate({
        cohort_size: cohortSize,
        criteria,
        seed_object_key: seedKey,
        trial_name: trialName || null,
        preview_features: 5,
      });
      setJobId(job.job_id);
    } catch (cause) {
      setError(
        cause instanceof ApiRequestError
          ? cause.message
          : "The generation job could not be queued.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (jobId) {
    return (
      <div className={cn("flex flex-col gap-4 p-6", className)}>
        <GenerationProgress
          jobId={jobId}
          onComplete={(job) => {
            if (job.status === "succeeded") {
              // Give the operator a moment to read the final stage list
              // before the page changes under them.
              setTimeout(() => router.push(`/cohorts/${job.job_id}`), 1200);
            }
          }}
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => router.push(`/cohorts/${jobId}`)}
            className="btn btn-secondary"
          >
            open cohort
          </button>
          <button type="button" onClick={() => setJobId(null)} className="btn btn-ghost">
            build another
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("grid grid-cols-1 gap-4 p-6 xl:grid-cols-[minmax(0,1fr)_360px]", className)}>
      <div className="flex min-w-0 flex-col gap-4">
        <SeedDataUploader
          onUploaded={(key, profile) => {
            setSeedKey(key);
            setSeedProfile(profile);
            // Criteria written against the reference schema are meaningless
            // once a real seed defines a different one.
            setCriteria([]);
          }}
          onCleared={() => {
            setSeedKey(null);
            setSeedProfile(null);
            setCriteria([]);
          }}
        />

        <CriteriaConfigurator
          features={features}
          criteria={criteria}
          onChange={setCriteria}
        />
      </div>

      <div className="flex flex-col gap-4">
        <div className="panel">
          <div className="panel-header">
            <span className="label-micro">trial</span>
          </div>
          <div className="space-y-4 p-4">
            <div>
              <label className="label-micro mb-1.5 block" htmlFor="trial-name">
                protocol name
              </label>
              <input
                id="trial-name"
                className="field"
                placeholder="CV-OUTCOMES-3"
                value={trialName}
                onChange={(event) => setTrialName(event.target.value)}
              />
            </div>

            <div>
              <label className="label-micro mb-1.5 block" htmlFor="cohort-size">
                target eligible patients
              </label>
              <input
                id="cohort-size"
                type="number"
                min={1}
                max={500000}
                className="field-mono"
                value={cohortSize}
                onChange={(event) => setCohortSize(Number(event.target.value) || 0)}
              />
              <div className="mt-2 flex gap-1">
                {SIZE_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setCohortSize(preset)}
                    className={cn(
                      "tabular border px-2 py-1 text-[11px] transition-colors",
                      cohortSize === preset
                        ? "border-accent text-accent-bright"
                        : "border-edge text-ink-dim hover:border-edge-strong hover:text-ink-muted",
                    )}
                  >
                    {formatCount(preset)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="label-micro">run summary</span>
          </div>
          <dl className="divide-y divide-edge-faint">
            <SummaryRow
              label="seed"
              value={seedProfile ? `${formatCount(seedProfile.rows)} rows` : "reference population"}
              tone={seedProfile ? "normal" : "muted"}
            />
            <SummaryRow label="features" value={formatCount(features.length)} />
            <SummaryRow label="criteria" value={formatCount(criteria.length)} />
            <SummaryRow label="target size" value={formatCount(cohortSize)} />
          </dl>

          {!seedProfile && (
            <p className="border-t border-edge px-4 py-2.5 text-xs text-ink-dim">
              No seed uploaded. The run will use the built in reference population,
              which is a demo fixture and is not derived from patient records.
            </p>
          )}

          <div className="border-t border-edge p-3">
            <button
              type="button"
              onClick={submit}
              disabled={submitting || cohortSize < 1}
              className="btn btn-primary w-full"
            >
              {submitting ? "queueing" : "generate cohort"}
            </button>
          </div>

          {error && (
            <div className="border-t border-signal-fail px-4 py-3">
              <div className="label-micro mb-1 text-signal-fail">not queued</div>
              <p className="text-sm text-ink">{error}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  tone = "normal",
}: {
  label: string;
  value: string;
  tone?: "normal" | "muted";
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <dt className="label-micro">{label}</dt>
      <dd
        className={cn(
          "tabular text-sm",
          tone === "muted" ? "text-ink-muted" : "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}
