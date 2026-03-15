import type {
  Belief,
  BeliefDiff,
  CatalogPreviewResponse,
  CatalogSearchResult,
  CasefileSummary,
  DeleteDrugResponse,
  Drug,
  DrugProfile,
  EpisodicSummary,
  ErrorResponse,
  FAERSReport,
  FDAAction,
  ForesightMemoryStatus,
  HealthResponse,
  IngestStatus,
  IngestProgress,
  IngestProgressMessage,
  MemoryProxyResponse,
  OnboardDrugResponse,
  QueryResponse,
  ScorecardEntry,
  SignalPoint,
  SituationAnalysis,
  TrackingJob,
} from "../types/shared";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
const inFlightGetRequests = new Map<string, Promise<unknown>>();

export interface SeedDemoResponse {
  seeded_drugs: string[];
  preload_quarters: string[];
  reports_loaded: number;
  reports_by_drug: Record<string, number>;
}

export class ApiError extends Error {
  public readonly statusCode: number;
  public readonly payload: ErrorResponse | null;

  constructor(message: string, statusCode: number, payload: ErrorResponse | null) {
    super(message);
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

function resolveUrl(path: string): string {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function parseJsonSafe(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function buildInFlightGetRequestKey(path: string, init: RequestInit): string | null {
  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET" || init.signal) {
    return null;
  }
  return resolveUrl(path);
}

async function requestJsonUncached<T>(
  path: string,
  init: RequestInit = {},
  retryAttempted = false,
): Promise<T> {
  let response: Response;

  try {
    response = await fetch(resolveUrl(path), {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    if (!retryAttempted) {
      await sleep(500);
      return requestJson<T>(path, init, true);
    }
    throw error;
  }

  if (response.ok) {
    return (await response.json()) as T;
  }

  const payload = (await parseJsonSafe(response)) as ErrorResponse | null;
  const isServerError = response.status >= 500;
  if (isServerError && !retryAttempted) {
    await sleep(500);
    return requestJson<T>(path, init, true);
  }

  throw new ApiError(
    payload?.detail ?? `Request failed with status ${response.status}`,
    response.status,
    payload,
  );
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  retryAttempted = false,
): Promise<T> {
  const cacheKey = retryAttempted ? null : buildInFlightGetRequestKey(path, init);
  if (!cacheKey) {
    return requestJsonUncached<T>(path, init, retryAttempted);
  }

  const pending = inFlightGetRequests.get(cacheKey);
  if (pending) {
    return pending as Promise<T>;
  }

  const request = requestJsonUncached<T>(path, init, retryAttempted).finally(() => {
    inFlightGetRequests.delete(cacheKey);
  });
  inFlightGetRequests.set(cacheKey, request);
  return request;
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health", { method: "GET", signal });
}

export async function getIngestStatus(drugId: string, signal?: AbortSignal): Promise<IngestStatus> {
  const params = new URLSearchParams({ drug_id: drugId });
  return requestJson<IngestStatus>(`/api/v1/ingest/status?${params.toString()}`, {
    method: "GET",
    signal,
  });
}

export async function getDrugs(signal?: AbortSignal): Promise<Drug[]> {
  return requestJson<Drug[]>("/api/v1/drugs", { method: "GET", signal });
}

export async function postSeedDemo(
  payload: {
    drugIds: string[];
    preloadQuarters: string[];
    dataDir?: string;
  },
  signal?: AbortSignal,
): Promise<SeedDemoResponse> {
  return requestJson<SeedDemoResponse>("/api/v1/admin/seed-demo", {
    method: "POST",
    signal,
    body: JSON.stringify({
      drug_ids: payload.drugIds,
      preload_quarters: payload.preloadQuarters,
      ...(payload.dataDir ? { data_dir: payload.dataDir } : {}),
    }),
  });
}

export async function deleteDrug(drugId: string, signal?: AbortSignal): Promise<DeleteDrugResponse> {
  return requestJson<DeleteDrugResponse>(`/api/v1/drugs/${drugId}`, {
    method: "DELETE",
    signal,
  });
}

export async function postDrugFullHistoryRebuildJob(
  drugId: string,
  payload: {
    baselineQuarters?: number;
    preferCached?: boolean;
  } = {},
  signal?: AbortSignal,
): Promise<TrackingJob> {
  return requestJson<TrackingJob>(`/api/v1/drugs/${encodeURIComponent(drugId)}/rebuild-full-history`, {
    method: "POST",
    signal,
    body: JSON.stringify({
      baseline_quarters: payload.baselineQuarters ?? 4,
      prefer_cached: payload.preferCached ?? false,
    }),
  });
}

export async function getActiveDrugFullHistoryRebuildJob(
  drugId: string,
  signal?: AbortSignal,
): Promise<TrackingJob> {
  return requestJson<TrackingJob>(`/api/v1/drugs/${encodeURIComponent(drugId)}/rebuild-full-history`, {
    method: "GET",
    signal,
  });
}

export async function getCatalogSearch(
  query: string,
  signal?: AbortSignal,
): Promise<CatalogSearchResult[]> {
  const params = new URLSearchParams({ q: query });
  return requestJson<CatalogSearchResult[]>(`/api/v1/catalog/search?${params.toString()}`, {
    method: "GET",
    signal,
  });
}

export async function getCatalogPreview(
  name: string,
  signal?: AbortSignal,
): Promise<CatalogPreviewResponse> {
  const params = new URLSearchParams({ name });
  return requestJson<CatalogPreviewResponse>(`/api/v1/catalog/preview?${params.toString()}`, {
    method: "GET",
    signal,
  });
}

export async function postIngestNextQuarter(drugId: string, signal?: AbortSignal): Promise<IngestStatus> {
  return requestJson<IngestStatus>("/api/v1/ingest/next-quarter", {
    method: "POST",
    signal,
    body: JSON.stringify({ drug_id: drugId }),
  });
}

export async function postIngestReset(
  drugId: string,
  hard = false,
  signal?: AbortSignal,
): Promise<IngestStatus> {
  return requestJson<IngestStatus>("/api/v1/ingest/reset", {
    method: "POST",
    signal,
    body: JSON.stringify({ drug_id: drugId, hard }),
  });
}

export async function getTimeline(
  drugId: string,
  events: string[] = [],
  signal?: AbortSignal,
): Promise<SignalPoint[]> {
  const params = new URLSearchParams();
  if (events.length > 0) {
    params.set("events", events.join(","));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SignalPoint[]>(`/api/v1/drugs/${drugId}/timeline${suffix}`, {
    method: "GET",
    signal,
  });
}

export async function getProfile(drugId: string, signal?: AbortSignal): Promise<DrugProfile> {
  return requestJson<DrugProfile>(`/api/v1/drugs/${drugId}/profile`, {
    method: "GET",
    signal,
  });
}

export async function getSignals(drugId: string, signal?: AbortSignal): Promise<SignalPoint[]> {
  return requestJson<SignalPoint[]>(`/api/v1/drugs/${drugId}/signals`, {
    method: "GET",
    signal,
  });
}

export async function getCasefileSummary(
  drugId: string,
  quarter?: string | null,
  signal?: AbortSignal,
): Promise<CasefileSummary> {
  const params = new URLSearchParams();
  if (quarter) {
    params.set("quarter", quarter);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<CasefileSummary>(`/api/v1/drugs/${drugId}/casefile-summary${suffix}`, {
    method: "GET",
    signal,
  });
}

export async function getEpisodes(drugId: string, signal?: AbortSignal): Promise<EpisodicSummary[]> {
  return requestJson<EpisodicSummary[]>(`/api/v1/drugs/${drugId}/episodes`, {
    method: "GET",
    signal,
  });
}

export async function getFdaActions(drugId: string, signal?: AbortSignal): Promise<FDAAction[]> {
  return requestJson<FDAAction[]>(`/api/v1/drugs/${drugId}/fda-actions`, {
    method: "GET",
    signal,
  });
}

export async function getScorecard(drugId: string, signal?: AbortSignal): Promise<ScorecardEntry[]> {
  return requestJson<ScorecardEntry[]>(`/api/v1/drugs/${drugId}/scorecard`, {
    method: "GET",
    signal,
  });
}

export async function getForesightStatus(
  drugId: string,
  signal?: AbortSignal,
): Promise<ForesightMemoryStatus> {
  return requestJson<ForesightMemoryStatus>(`/api/v1/drugs/${drugId}/foresight-status`, {
    method: "GET",
    signal,
  });
}

export async function getBeliefs(drugId: string, signal?: AbortSignal): Promise<Belief[]> {
  return requestJson<Belief[]>(`/api/v1/beliefs/${drugId}`, {
    method: "GET",
    signal,
  });
}

export async function getBeliefDiff(
  drugId: string,
  beforeId: string,
  afterId: string,
  signal?: AbortSignal,
): Promise<BeliefDiff> {
  const params = new URLSearchParams({ before_id: beforeId, after_id: afterId });
  return requestJson<BeliefDiff>(`/api/v1/beliefs/${drugId}/diff?${params.toString()}`, {
    method: "GET",
    signal,
  });
}

export async function getEvidence(reportId: string, signal?: AbortSignal): Promise<FAERSReport> {
  return requestJson<FAERSReport>(`/api/v1/evidence/${reportId}`, {
    method: "GET",
    signal,
  });
}

export async function postQuery(
  drugId: string,
  questionText: string,
  quarterContext?: string,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  return requestJson<QueryResponse>("/api/v1/query", {
    method: "POST",
    signal,
    body: JSON.stringify({
      drug_id: drugId,
      question_text: questionText,
      quarter_context: quarterContext,
    }),
  });
}

export async function getSituationAnalysis(
  drugId: string,
  quarter?: string,
  signal?: AbortSignal,
): Promise<SituationAnalysis> {
  const params = new URLSearchParams();
  if (quarter) {
    params.set("quarter", quarter);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<SituationAnalysis>(`/api/v1/drugs/${drugId}/situation${suffix}`, {
    method: "GET",
    signal,
  });
}

export async function getMemoryProxy(
  drugId: string,
  memoryId: string,
  refresh = false,
  signal?: AbortSignal,
): Promise<MemoryProxyResponse> {
  const params = new URLSearchParams({
    drug_id: drugId,
    refresh: refresh ? "true" : "false",
  });
  return requestJson<MemoryProxyResponse>(
    `/api/v1/memory-proxy/${encodeURIComponent(memoryId)}?${params.toString()}`,
    {
      method: "GET",
      signal,
    },
  );
}

export async function postTrackingOnboard(
  payload: {
    medicationName: string;
    baselineQuarters?: number;
    maxReports?: number;
    preferCached?: boolean;
  },
  signal?: AbortSignal,
): Promise<OnboardDrugResponse> {
  return requestJson<OnboardDrugResponse>("/api/v1/tracking/onboard", {
    method: "POST",
    signal,
    body: JSON.stringify({
      medication_name: payload.medicationName,
      baseline_quarters: payload.baselineQuarters ?? 4,
      max_reports: payload.maxReports ?? 1500,
      prefer_cached: payload.preferCached ?? true,
    }),
  });
}

export async function postTrackingJob(
  payload: {
    medicationName: string;
    baselineQuarters?: number;
    maxReports?: number;
    preferCached?: boolean;
  },
  signal?: AbortSignal,
): Promise<TrackingJob> {
  return requestJson<TrackingJob>("/api/v1/tracking/jobs", {
    method: "POST",
    signal,
    body: JSON.stringify({
      medication_name: payload.medicationName,
      baseline_quarters: payload.baselineQuarters ?? 4,
      max_reports: payload.maxReports ?? 1500,
      prefer_cached: payload.preferCached ?? true,
    }),
  });
}

export async function getTrackingJob(jobId: string, signal?: AbortSignal): Promise<TrackingJob> {
  return requestJson<TrackingJob>(`/api/v1/tracking/jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
    signal,
  });
}

export function buildIngestWsUrl(drugId: string): string {
  const rawBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
  if (!rawBase) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/ingest-progress?drug_id=${encodeURIComponent(drugId)}`;
  }

  const url = new URL(rawBase);
  const wsProtocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProtocol}//${url.host}/ws/ingest-progress?drug_id=${encodeURIComponent(drugId)}`;
}

export function parseIngestProgress(payload: unknown): IngestProgress | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const looksLikeProgressMessage = (candidate: unknown): candidate is IngestProgressMessage => {
    if (!candidate || typeof candidate !== "object") {
      return false;
    }
    const row = candidate as Record<string, unknown>;
    return (
      typeof row.phase === "string" &&
      typeof row.quarter === "string" &&
      typeof row.reports_processed === "number" &&
      typeof row.total_reports === "number" &&
      typeof row.signals_updated === "number" &&
      typeof row.evermemos_consolidation_status === "string"
    );
  };

  const maybe = payload as Record<string, unknown>;
  if (looksLikeProgressMessage(maybe.message)) {
    return { message: maybe.message };
  }
  // Backward-compatible fallback when server emits the message shape directly.
  if (looksLikeProgressMessage(maybe)) {
    return { message: maybe };
  }
  return null;
}
