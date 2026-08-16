import type {
  ApiEnvelope,
  CohortJob,
  ExportFormat,
  ExportResult,
  FidelityReport,
  GenerateRequest,
} from "@pretrial/shared-types";

/**
 * Client for the three services.
 *
 * Every service answers in the same { data, error, meta } envelope, so
 * unwrapping happens once here and callers deal in plain values or a thrown
 * ApiRequestError. Threading the envelope through the component tree would
 * mean every consumer re-implementing the same null check.
 */

export const SYNTHECORE_URL =
  process.env.NEXT_PUBLIC_SYNTHECORE_URL ?? "http://localhost:8001";
export const FIDELITYCHECK_URL =
  process.env.NEXT_PUBLIC_FIDELITYCHECK_URL ?? "http://localhost:8002";
export const FHIRLINK_URL =
  process.env.NEXT_PUBLIC_FHIRLINK_URL ?? "http://localhost:8003";

/** Row shape returned by the job list endpoint. */
export interface CohortSummary {
  job_id: string;
  status: CohortJob["status"];
  percent: number;
  stage_label: string | null;
  message: string;
  created_at: number;
  updated_at: number;
  cohort_size: number | null;
  features: number;
  engine: string | null;
  is_stub: boolean | null;
  overall_fidelity: number | null;
  grade: import("@pretrial/shared-types").FidelityGrade | null;
  duration_seconds: number | null;
}

export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options: { code: string; status: number; details?: unknown; requestId?: string },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
    this.requestId = options.requestId;
  }
}

async function request<T>(
  url: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  // A generation request that hangs should surface as an error the UI can
  // show, not as a spinner that never resolves.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), init?.timeoutMs ?? 120_000);

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    clearTimeout(timeout);
    const aborted = cause instanceof DOMException && cause.name === "AbortError";
    throw new ApiRequestError(
      aborted ? "The request timed out." : "The service could not be reached.",
      { code: aborted ? "timeout" : "network_error", status: 0, details: String(cause) },
    );
  }
  clearTimeout(timeout);

  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiRequestError("The service returned a response that was not JSON.", {
      code: "malformed_response",
      status: response.status,
    });
  }

  if (envelope.error || envelope.data === null) {
    throw new ApiRequestError(envelope.error?.message ?? "The request failed.", {
      code: envelope.error?.code ?? "unknown_error",
      status: response.status,
      details: envelope.error?.details,
      requestId: envelope.meta?.request_id,
    });
  }

  return envelope.data;
}

/* -------------------------------------------------------------------------
 * SyntheCore
 * ---------------------------------------------------------------------- */

export const synthecore = {
  generate(payload: GenerateRequest): Promise<CohortJob> {
    return request<CohortJob>(`${SYNTHECORE_URL}/generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  job(jobId: string): Promise<CohortJob> {
    return request<CohortJob>(`${SYNTHECORE_URL}/jobs/${jobId}`, { method: "GET" });
  },

  jobs(limit = 50): Promise<{ jobs: CohortSummary[] }> {
    return request<{ jobs: CohortSummary[] }>(`${SYNTHECORE_URL}/jobs?limit=${limit}`, {
      method: "GET",
    });
  },

  cohort(jobId: string, limit = 1000, offset = 0) {
    return request<{
      job_id: string;
      features: string[];
      rows: Record<string, unknown>[];
    }>(`${SYNTHECORE_URL}/jobs/${jobId}/cohort?limit=${limit}&offset=${offset}`, {
      method: "GET",
    });
  },

  engine() {
    return request<{ engine: string; is_stub: boolean; method: string; warning: string | null }>(
      `${SYNTHECORE_URL}/engine`,
      { method: "GET" },
    );
  },

  /** Seed upload is multipart, so it does not go through `request`. */
  async uploadSeed(file: File) {
    const body = new FormData();
    body.append("file", file);

    const response = await fetch(`${SYNTHECORE_URL}/seed/upload`, { method: "POST", body });
    const envelope = (await response.json()) as ApiEnvelope<{
      seed_object_key: string;
      profile: import("@pretrial/shared-types").SeedProfile;
      sample_schema: Record<string, string>;
    }>;

    if (envelope.error || !envelope.data) {
      throw new ApiRequestError(envelope.error?.message ?? "Seed upload failed.", {
        code: envelope.error?.code ?? "upload_failed",
        status: response.status,
        details: envelope.error?.details,
      });
    }
    return envelope.data;
  },

  /** SSE endpoint for live job progress. Consumed by GenerationProgress. */
  streamUrl(jobId: string): string {
    return `${SYNTHECORE_URL}/jobs/${jobId}/stream`;
  },
};

/* -------------------------------------------------------------------------
 * FidelityCheck
 * ---------------------------------------------------------------------- */

export const fidelitycheck = {
  validate(payload: {
    real: Record<string, unknown>[];
    synthetic: Record<string, unknown>[];
    features?: string[];
    alpha?: number;
    preview_features?: number;
    cohort_id?: string;
  }): Promise<FidelityReport> {
    return request<FidelityReport>(`${FIDELITYCHECK_URL}/validate`, {
      method: "POST",
      body: JSON.stringify(payload),
      // Validation on a large cohort is CPU bound and can outrun the
      // default timeout.
      timeoutMs: 300_000,
    });
  },
};

/* -------------------------------------------------------------------------
 * FHIR-Link
 * ---------------------------------------------------------------------- */

export const fhirlink = {
  formats(): Promise<{ formats: ExportFormat[] }> {
    return request<{ formats: ExportFormat[] }>(`${FHIRLINK_URL}/formats`, {
      method: "GET",
    });
  },

  export(payload: {
    rows: Record<string, unknown>[];
    cohort_id: string;
    format: string;
    include_observations?: boolean;
    fidelity_score?: number;
    acknowledge_low_fidelity?: boolean;
  }): Promise<ExportResult> {
    return request<ExportResult>(`${FHIRLINK_URL}/export`, {
      method: "POST",
      body: JSON.stringify(payload),
      timeoutMs: 300_000,
    });
  },

  preview(payload: {
    rows: Record<string, unknown>[];
    cohort_id: string;
    format: string;
    limit?: number;
  }) {
    return request<{
      cohort_id: string;
      format: ExportFormat;
      content: string;
      bundle?: import("@pretrial/shared-types").BundleReport;
      patients_in_preview: number;
      patients_total: number;
    }>(`${FHIRLINK_URL}/export/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
