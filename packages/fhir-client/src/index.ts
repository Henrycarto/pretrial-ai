/**
 * A small read side FHIR client.
 *
 * This is not a general purpose FHIR library. It covers the two things
 * Pretrial.ai does with FHIR from the browser: inspect a bundle that
 * FHIR-Link produced, and push a bundle to a hospital FHIR endpoint using a
 * SMART on FHIR access token. Anything beyond that belongs in a full client.
 */

import type { BundleReport, ExportFormat } from "@pretrial/shared-types";

export const HTEST_SECURITY_CODE = "HTEST";
export const SECURITY_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActReason";

export interface FhirCoding {
  system?: string;
  code?: string;
  display?: string;
}

export interface FhirMeta {
  security?: FhirCoding[];
  tag?: FhirCoding[];
}

export interface FhirResource {
  resourceType: string;
  id?: string;
  meta?: FhirMeta;
  [key: string]: unknown;
}

export interface FhirBundleEntry {
  fullUrl?: string;
  resource?: FhirResource;
  request?: { method: string; url: string };
}

export interface FhirBundle extends FhirResource {
  resourceType: "Bundle";
  type: string;
  timestamp?: string;
  entry?: FhirBundleEntry[];
}

/** Counts by resourceType, for the preview panel header. */
export function countResources(bundle: FhirBundle): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const entry of bundle.entry ?? []) {
    const type = entry.resource?.resourceType;
    if (!type) continue;
    counts[type] = (counts[type] ?? 0) + 1;
  }
  return counts;
}

/**
 * Whether every resource carries the synthetic data marker.
 *
 * Checked in the browser as well as in the service. An untagged synthetic
 * record reaching a production data warehouse is the single worst outcome
 * this product can produce, so it is worth verifying at both ends rather
 * than trusting that the service did its job.
 */
export function isMarkedSynthetic(bundle: FhirBundle): boolean {
  const entries = bundle.entry ?? [];
  if (entries.length === 0) return false;
  return entries.every((entry) =>
    entry.resource?.meta?.security?.some(
      (coding) => coding.code === HTEST_SECURITY_CODE && coding.system === SECURITY_SYSTEM,
    ),
  );
}

/** Resources missing the marker, so the UI can name them rather than just warn. */
export function unmarkedResources(bundle: FhirBundle): string[] {
  return (bundle.entry ?? [])
    .filter(
      (entry) =>
        !entry.resource?.meta?.security?.some(
          (coding) => coding.code === HTEST_SECURITY_CODE,
        ),
    )
    .map((entry) => `${entry.resource?.resourceType ?? "unknown"}/${entry.resource?.id ?? "?"}`);
}

export function parseBundle(raw: string): FhirBundle {
  const parsed = JSON.parse(raw) as FhirBundle;
  if (parsed.resourceType !== "Bundle") {
    throw new Error(`expected a Bundle, received ${parsed.resourceType}`);
  }
  return parsed;
}

/** NDJSON exports are a resource per line, not a bundle. */
export function parseNdjson(raw: string): FhirResource[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as FhirResource);
}

export interface PushOptions {
  endpoint: string;
  /** SMART on FHIR bearer token. Never persisted by this client. */
  accessToken: string;
  bundle: FhirBundle;
  signal?: AbortSignal;
}

export interface PushOutcome {
  ok: boolean;
  status: number;
  /** The server's OperationOutcome or Bundle response, unparsed. */
  body: string;
}

/**
 * POST a transaction bundle to a FHIR server root.
 *
 * Refuses to send a bundle that is not fully marked as test data. That check
 * is not configurable: this function's whole job is putting synthetic records
 * into a system that holds real ones.
 */
export async function pushBundle(options: PushOptions): Promise<PushOutcome> {
  if (!isMarkedSynthetic(options.bundle)) {
    throw new Error(
      "Refusing to push: one or more resources are missing the HTEST synthetic " +
        `data marker (${unmarkedResources(options.bundle).slice(0, 3).join(", ")})`,
    );
  }

  const response = await fetch(options.endpoint.replace(/\/$/, ""), {
    method: "POST",
    headers: {
      "Content-Type": "application/fhir+json",
      Accept: "application/fhir+json",
      Authorization: `Bearer ${options.accessToken}`,
    },
    body: JSON.stringify(options.bundle),
    signal: options.signal,
  });

  return {
    ok: response.ok,
    status: response.status,
    body: await response.text(),
  };
}

/** Trigger a browser download of an export the user already has in memory. */
export function downloadExport(
  content: string,
  filename: string,
  format: Pick<ExportFormat, "media_type">,
): void {
  const blob = new Blob([content], { type: format.media_type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  // Revoking immediately cancels the download in Safari, so this waits a
  // tick rather than releasing the object URL synchronously.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type { BundleReport, ExportFormat };
