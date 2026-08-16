"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { FidelityReport } from "@pretrial/shared-types";

import { ValidationReport } from "@/components/fidelity/ValidationReport";
import { PageHeader } from "@/components/ui/AppShell";
import { synthecore } from "@/lib/api";

/**
 * The full validation report for a cohort.
 *
 * The report is read from the job record rather than recomputed. Running the
 * tests again on page load would produce a slightly different number every
 * visit once sampling is involved, and a fidelity score that moves between
 * views is not defensible in a review meeting.
 */
export default function ValidationPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;

  const [report, setReport] = useState<FidelityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    synthecore
      .job(jobId)
      .then((job) => {
        if (cancelled) return;
        const validation = job.result?.validation;
        if (validation?.status === "complete" && validation.report) {
          setReport(validation.report);
        } else {
          setError(
            validation?.reason ??
              "No validation report was recorded for this cohort.",
          );
        }
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

  return (
    <>
      <PageHeader
        title="Validation report"
        subtitle={jobId}
        actions={
          <Link href={`/cohorts/${jobId}`} className="btn btn-secondary">
            back to cohort
          </Link>
        }
      />

      <div className="p-6">
        {error && (
          <div className="panel px-4 py-4">
            <div className="label-micro mb-1.5 text-signal-warn">no report</div>
            <p className="text-sm text-ink-muted">{error}</p>
          </div>
        )}

        {!error && !report && (
          <div className="panel px-4 py-6">
            <span className="label-micro">loading report</span>
          </div>
        )}

        {report && <ValidationReport report={report} />}
      </div>
    </>
  );
}
