/**
 * FHIR helpers for the web app.
 *
 * Resource construction happens in FHIR-Link, in Python, against a library
 * that validates. This module is the read side only: describing, counting,
 * and flattening bundles the service already produced. Building FHIR
 * resources in the browser would put a second, unvalidated implementation of
 * the mapping in the codebase, and the two would drift.
 */

import {
  countResources,
  isMarkedSynthetic,
  parseBundle,
  parseNdjson,
  unmarkedResources,
  type FhirBundle,
  type FhirResource,
} from "@pretrial/fhir-client";

export {
  countResources,
  isMarkedSynthetic,
  parseBundle,
  parseNdjson,
  unmarkedResources,
};
export type { FhirBundle, FhirResource };

export const LOINC_SYSTEM = "http://loinc.org";
export const LOCAL_FEATURE_SYSTEM = "https://pretrial.ai/fhir/CodeSystem/cohort-feature";

export interface ObservationSummary {
  patientId: string;
  feature: string;
  code: string;
  system: string;
  value: number | string | boolean | null;
  unit: string | null;
  /** False when the code came from the Pretrial.ai local system. */
  standardCoded: boolean;
}

/** Pull observations out of a bundle into a flat, tabular shape. */
export function flattenObservations(bundle: FhirBundle): ObservationSummary[] {
  const summaries: ObservationSummary[] = [];

  for (const entry of bundle.entry ?? []) {
    const resource = entry.resource;
    if (!resource || resource.resourceType !== "Observation") continue;

    const code = resource.code as
      | { coding?: { system?: string; code?: string }[]; text?: string }
      | undefined;
    const coding = code?.coding?.[0];
    const subject = resource.subject as { reference?: string } | undefined;
    const quantity = resource.valueQuantity as
      | { value?: number; unit?: string }
      | undefined;

    let value: number | string | boolean | null = null;
    if (quantity?.value !== undefined) value = quantity.value;
    else if (typeof resource.valueBoolean === "boolean") value = resource.valueBoolean;
    else if (typeof resource.valueString === "string") value = resource.valueString;

    summaries.push({
      patientId: subject?.reference?.split("/")[1] ?? "unknown",
      feature: code?.text ?? coding?.code ?? "unknown",
      code: coding?.code ?? "",
      system: coding?.system ?? "",
      value,
      unit: quantity?.unit ?? null,
      standardCoded: coding?.system === LOINC_SYSTEM,
    });
  }

  return summaries;
}

/**
 * Rebuild a patient by patient table from a bundle.
 *
 * Useful for showing a reviewer that the bundle round trips back to the rows
 * they started with, which is a question that comes up in every integration
 * conversation.
 */
export function bundleToRows(bundle: FhirBundle): Record<string, unknown>[] {
  const byPatient = new Map<string, Record<string, unknown>>();

  for (const entry of bundle.entry ?? []) {
    const resource = entry.resource;
    if (resource?.resourceType !== "Patient" || !resource.id) continue;
    byPatient.set(resource.id, {
      patient_id: resource.id,
      gender: resource.gender ?? null,
      birth_date: resource.birthDate ?? null,
    });
  }

  for (const observation of flattenObservations(bundle)) {
    const row = byPatient.get(observation.patientId);
    if (row) row[observation.feature] = observation.value;
  }

  return [...byPatient.values()];
}

/** Human readable one line description of a bundle, for headers and logs. */
export function describeBundle(bundle: FhirBundle): string {
  const counts = countResources(bundle);
  const parts = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${count} ${type}`);
  return `${bundle.type} bundle, ${parts.join(", ")}`;
}

/** Features in the bundle that carry a non standard code. */
export function locallyCodedFeatures(bundle: FhirBundle): string[] {
  const features = new Set<string>();
  for (const observation of flattenObservations(bundle)) {
    if (!observation.standardCoded) features.add(observation.feature);
  }
  return [...features].sort();
}
