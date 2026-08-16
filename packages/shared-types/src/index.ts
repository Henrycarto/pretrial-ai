/**
 * Types shared between the web app and the Python services.
 *
 * These mirror the Pydantic models in each service's app/schemas.py. They are
 * hand written rather than generated from the OpenAPI documents because the
 * generated output for the report payload is close to unreadable, and this
 * file is read far more often than it is changed. When a service schema
 * changes, this file changes with it in the same commit.
 */

/** Every service response, success or failure, arrives in this shape. */
export interface ApiEnvelope<T> {
  data: T | null;
  error: ApiError | null;
  meta: ApiMeta;
}

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiMeta {
  service: string;
  version: string;
  request_id: string;
  duration_ms?: number;
  [key: string]: unknown;
}

/* -------------------------------------------------------------------------
 * FidelityCheck
 * ---------------------------------------------------------------------- */

export type FidelityGrade = "pass" | "borderline" | "fail";

/**
 * Thresholds are duplicated from report_builder.py on purpose, and the ring
 * colour in FidelityScoreBadge reads them from here. Changing one side
 * without the other puts a green ring on a failing cohort, so both files
 * carry a comment pointing at the other.
 */
export const FIDELITY_THRESHOLDS = {
  pass: 90,
  borderline: 70,
} as const;

export function gradeForScore(score: number): FidelityGrade {
  if (score >= FIDELITY_THRESHOLDS.pass) return "pass";
  if (score >= FIDELITY_THRESHOLDS.borderline) return "borderline";
  return "fail";
}

export type FeatureKind = "numeric" | "categorical" | "unsupported";

export interface FeatureFidelity {
  feature: string;
  kind: FeatureKind;
  fidelity: number;
  ks_statistic: number | null;
  ks_p_value: number | null;
  js_divergence: number | null;
  n_real: number;
  n_synthetic: number;
  grade: FidelityGrade | "not_evaluated";
  evaluated: boolean;
  note: string | null;
}

export interface DistributionPreview {
  feature: string;
  kind: FeatureKind;
  fidelity: number;
  bins: string[];
  real: number[];
  synthetic: number[];
  bin_edges: number[];
}

export interface CorrelationPair {
  feature_a: string;
  feature_b: string;
  real: number;
  synthetic: number;
  delta: number;
}

export interface CorrelationComparison {
  method: string;
  features: string[];
  matrix_features: string[];
  real_matrix: (number | null)[][];
  synthetic_matrix: (number | null)[][];
  delta_matrix: (number | null)[][];
  mean_absolute_delta: number;
  /** The summary the dependency score is actually built from. */
  rms_delta: number;
  max_absolute_delta: number;
  frobenius_norm: number;
  pairs_compared: number;
  score: number;
  evaluated: boolean;
  worst_pairs: CorrelationPair[];
  note: string | null;
}

export interface FidelityComponents {
  marginal_agreement: number | null;
  shape_agreement: number | null;
  dependency_structure: number | null;
  schema_coverage: number;
}

export interface SchemaAlignment {
  shared: string[];
  real_only: string[];
  synthetic_only: string[];
  coverage: number;
  feature_kinds: Record<string, FeatureKind>;
}

export interface FidelityReport {
  overall_fidelity: number;
  /** Score before the schema coverage multiplier is applied. */
  raw_fidelity: number;
  grade: FidelityGrade;
  verdict: string;
  components: FidelityComponents;
  weights: Record<string, number>;
  schema_alignment: SchemaAlignment;
  features: FeatureFidelity[];
  ks_results: Record<string, unknown>[];
  js_results: Record<string, unknown>[];
  correlation: CorrelationComparison;
  distribution_previews: DistributionPreview[];
  distribution_preview_ranking: string;
  row_counts: { real: number; synthetic: number };
  warnings: string[];
  thresholds: { pass: number; borderline: number };
  cohort_id: string | null;
}

/* -------------------------------------------------------------------------
 * SyntheCore
 * ---------------------------------------------------------------------- */

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type StageStatus = "pending" | "running" | "done" | "failed";

/**
 * Stage keys and their order are fixed by progress.py in SyntheCore. The
 * progress component renders whatever the service sends rather than a
 * hardcoded list, so a new stage appears in the UI without a frontend
 * change, but the labels below are the fallback when a job record predates
 * a stage rename.
 */
export const STAGE_LABELS: Record<string, string> = {
  parse_seed: "Parsing seed data",
  train_model: "Training model",
  sample_cohort: "Sampling cohort",
  validate: "Running validation",
};

export interface JobStage {
  key: string;
  label: string;
  status: StageStatus;
  started_at: number | null;
  finished_at: number | null;
  detail: string | null;
}

export interface CohortJob {
  job_id: string;
  status: JobStatus;
  stage: string | null;
  stage_label: string | null;
  stage_index: number;
  stage_count: number;
  percent: number;
  message: string;
  created_at: number;
  updated_at: number;
  stages: JobStage[];
  result: CohortResult | null;
  error: ApiError | null;
}

export interface EngineInfo {
  name: string;
  is_stub: boolean;
  detail: string;
}

export interface FunnelStep {
  criterion: string;
  feature: string;
  kind: "inclusion" | "exclusion";
  candidates_in: number;
  removed: number;
  candidates_out: number;
  removal_rate: number;
  note: string | null;
}

export interface ScreeningSummary {
  candidates_screened: number;
  eligible: number;
  eligibility_rate: number;
  funnel: FunnelStep[];
  warnings: string[];
  attempts?: number;
  delivered?: number;
  note?: string;
}

export interface SeedProfile {
  rows: number;
  columns: number;
  feature_names: string[];
  numeric_features: string[];
  categorical_features: string[];
  dropped_identifiers: string[];
  dropped_free_text: string[];
  null_rates: Record<string, number>;
  warnings: string[];
  source?: string;
}

export interface CohortResult {
  job_id: string;
  cohort_size: number;
  requested_size: number;
  features: string[];
  engine: EngineInfo;
  seed_profile: SeedProfile;
  screening: ScreeningSummary;
  validation: {
    status: "complete" | "skipped" | "unavailable";
    overall_fidelity?: number;
    grade?: FidelityGrade;
    verdict?: string;
    components?: FidelityComponents;
    report?: FidelityReport;
    reason?: string;
  };
  storage: { backend: string; location: string };
  preview: Record<string, unknown>[];
  duration_seconds: number;
}

/* -------------------------------------------------------------------------
 * Criteria
 * ---------------------------------------------------------------------- */

export type CriterionOperator =
  | "gt" | "gte" | "lt" | "lte" | "eq" | "neq"
  | "in" | "not_in" | "between"
  | "is_true" | "is_false" | "is_null" | "not_null";

export interface Criterion {
  feature: string;
  operator: CriterionOperator;
  value?: unknown;
  kind: "inclusion" | "exclusion";
  label?: string;
}

/** Operators that take no value, so the builder hides the value input. */
export const UNARY_OPERATORS: CriterionOperator[] = [
  "is_true",
  "is_false",
  "is_null",
  "not_null",
];

export const OPERATOR_LABELS: Record<CriterionOperator, string> = {
  gt: "greater than",
  gte: "at least",
  lt: "less than",
  lte: "at most",
  eq: "equal to",
  neq: "not equal to",
  in: "one of",
  not_in: "not one of",
  between: "between",
  is_true: "is true",
  is_false: "is false",
  is_null: "is missing",
  not_null: "is recorded",
};

export interface GenerateRequest {
  cohort_size: number;
  criteria: Criterion[];
  seed_rows?: Record<string, unknown>[] | null;
  seed_object_key?: string | null;
  reference_cohort_size?: number;
  preview_features?: number;
  trial_name?: string | null;
  notes?: string | null;
}

/* -------------------------------------------------------------------------
 * FHIR-Link
 * ---------------------------------------------------------------------- */

export interface ExportFormat {
  id: string;
  label: string;
  media_type: string;
  extension: string;
  description: string;
  bundle_type: string | null;
  fhir: boolean;
  streamable: boolean;
}

export interface BundleReport {
  patients: number;
  observations: number;
  mapped_features: string[];
  unmapped_features: string[];
  skipped_features: string[];
  warnings: string[];
}

export interface ExportResult {
  cohort_id: string;
  filename: string;
  media_type: string;
  content: string;
  format: ExportFormat;
  bundle: BundleReport;
  size_bytes: number;
}
