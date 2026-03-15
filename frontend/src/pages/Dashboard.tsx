import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  ApiError,
  getActiveDrugFullHistoryRebuildJob,
  getBeliefDiff,
  getBeliefs,
  getCasefileSummary,
  getDrugs,
  getEpisodes,
  getEvidence,
  getForesightStatus,
  getFdaActions,
  getHealth,
  getIngestStatus,
  getTrackingJob,
  getProfile,
  getScorecard,
  getSignals,
  getTimeline,
  postSeedDemo,
  postDrugFullHistoryRebuildJob,
  postIngestNextQuarter,
  postIngestReset,
  postQuery,
} from "../api/client";
import { AboutPanel } from "../components/AboutPanel";
import {
  AgentThoughtStream,
  type AgentLogEntry as AgentThoughtLogEntry,
  type AgentRunState,
} from "../components/AgentThoughtStream";
import { BeliefDiff } from "../components/BeliefDiff";
import { DemoModeButton } from "../components/DemoModeButton";
import { CasefileIntro } from "../components/CasefileIntro";
import { DrugSelector } from "../components/DrugSelector";
import { EpisodicTimeline } from "../components/EpisodicTimeline";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { EvidenceSpotlight } from "../components/EvidenceSpotlight";
import { FirstLoadDemoEntrypoint } from "../components/FirstLoadDemoEntrypoint";
import { IngestButton } from "../components/IngestButton";
import { MetricsBar } from "../components/MetricsBar";
import { BeliefRevisionHero } from "../components/BeliefRevisionHero";
import { MemoryArchitectureCard } from "../components/MemoryArchitectureCard";
import { KnowledgeTimeExplorer } from "../components/KnowledgeTimeExplorer";
import { MemoryNecessityProof } from "../components/MemoryNecessityProof";
import {
  MemoryViewerModal,
  type MemoryViewerEntry,
} from "../components/MemoryViewerModal";
import { MemoryReasoningLoopTrace } from "../components/MemoryReasoningLoopTrace";
import { MemoryProvenance } from "../components/MemoryProvenance";
import { PredictionScorecard } from "../components/PredictionScorecard";
import { ProfileCard } from "../components/ProfileCard";
import { QueryInterface } from "../components/QueryInterface";
import {
  detectNewSignals,
  type SignalAlert,
  SignalAlertToast,
} from "../components/SignalAlertToast";
import { SignalTimeline } from "../components/SignalTimeline";
import { SituationAnalysisCard } from "../components/SituationAnalysisCard";
import { StoryHeader } from "../components/StoryHeader";
import { useIngestProgressSocket } from "../hooks/useIngestProgressSocket";
import {
  buildAutoEvidenceQuestion,
  pickBeliefPairForQuarterDiff,
  resolveSpotlightSignal,
} from "../lib/autoEvidence";
import {
  clearCachedResource,
  getCachedResource,
  seedCachedResource,
} from "../lib/resourceCache";
import {
  buildEventLogMemoryId,
  buildForesightMemoryId,
  buildProfileMemoryId,
} from "../lib/memoryProvenance";
import {
  getRebuildPollError,
  getRebuildStartErrorMessage,
} from "../lib/rebuildErrors";
import {
  clearPersistedRebuildJobId,
  persistRebuildJobId,
  readPersistedRebuildJobId,
} from "../lib/rebuildJobs";
import {
  buildDemoReceiptMetricSuffix,
  countScorecardEntries,
  splitScorecardEntries,
} from "../lib/scorecardPresentation";
import { projectScorecardAsOf } from "../lib/scorecardTimeline";
import {
  buildQueryEpisodicRecallThought,
  buildQueryForesightRecallThought,
  buildQueryBeliefThought,
  buildQuerySearchThought,
  buildQuarterSummaryThought,
  buildTimeTravelObservationThought,
  claimQuarterOnce,
  syntheticThoughtId,
} from "../lib/syntheticThoughts";
import { useVigilensStore } from "../store/useVigilensStore";
import type {
  AgentThought,
  Belief,
  CasefileSummary,
  EpisodicSummary,
  FAERSReport,
  ForesightMemoryStatus,
  QueryResponse,
  ScorecardEntry,
  SignalPoint,
  TrackingJob,
} from "../types/shared";

const MAX_TRAJECTORY_EVENTS = 10;
type BeliefTabKey = "safety" | "gi" | "regulatory";
type DemoStage = "baseline" | "reveal" | "validation" | "analyst";
type MemoryStatusTone = "ok" | "warning" | "idle";

const BASELINE_QUARTER = "2018-Q4";
const FAST_DEMO_QUARTER = "2023-Q2";
const REVEAL_QUARTER = "2023-Q3";
const VALIDATION_QUARTER = "2023-Q4";
const SEMAGLUTIDE_DEMO_BASELINE_QUARTERS = [
  "2018-Q1",
  "2018-Q2",
  "2018-Q3",
  "2018-Q4",
];
const FULL_DEMO_HISTORY_QUARTERS = [
  "2018-Q1",
  "2018-Q2",
  "2018-Q3",
  "2018-Q4",
  "2019-Q1",
  "2019-Q2",
  "2019-Q3",
  "2019-Q4",
  "2020-Q1",
  "2020-Q2",
  "2020-Q3",
  "2020-Q4",
  "2021-Q1",
  "2021-Q2",
  "2021-Q3",
  "2021-Q4",
  "2022-Q1",
  "2022-Q2",
  "2022-Q3",
  "2022-Q4",
  "2023-Q1",
  "2023-Q2",
  "2023-Q3",
  "2023-Q4",
];

type BeliefDiffResponse = Awaited<ReturnType<typeof getBeliefDiff>>;

function shimmerClass(): string {
  return "bg-[linear-gradient(110deg,rgba(26,26,31,0.8),rgba(212,149,106,0.08),rgba(26,26,31,0.8))] bg-[length:200%_100%] animate-shimmer rounded-xl";
}

function pickLatestBeliefPerQuestion(items: Belief[]): Belief[] {
  const byHash = new Map<string, Belief>();
  for (const item of items) {
    const current = byHash.get(item.question_hash);
    if (!current || current.created_at < item.created_at) {
      byHash.set(item.question_hash, item);
    }
  }
  return [...byHash.values()].sort((a, b) =>
    a.question_text.localeCompare(b.question_text),
  );
}

function isoDateToQuarter(value: string): string | null {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const quarter = Math.floor(parsed.getUTCMonth() / 3) + 1;
  return `${parsed.getUTCFullYear()}-Q${quarter}`;
}

function thoughtTypeToMemoryType(
  thoughtType: AgentThought["type"],
): MemoryViewerEntry["type"] {
  if (thoughtType === "foresight") {
    return "Foresight";
  }
  if (thoughtType === "memory_write") {
    return "Profile";
  }
  if (thoughtType === "memory_recall" || thoughtType === "memory_query") {
    return "Episodic";
  }
  return "EventLog";
}

function memoryTypeFromId(
  memoryId: string,
  thoughtType: AgentThought["type"],
): MemoryViewerEntry["type"] {
  const normalized = memoryId.toLowerCase();
  if (
    normalized.includes("_foresight") ||
    normalized.startsWith("foresight:")
  ) {
    return "Foresight";
  }
  if (normalized.includes("_profile") || normalized.startsWith("profile:")) {
    return "Profile";
  }
  if (
    normalized.includes("_eventlog_") ||
    normalized.endsWith("_eventlog") ||
    normalized.startsWith("eventlog:")
  ) {
    return "EventLog";
  }
  if (normalized.startsWith("episodic:")) {
    return "Episodic";
  }
  return thoughtTypeToMemoryType(thoughtType);
}

function formatBeliefSnapshot(answerText: string): string {
  const lines = answerText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (lines.length === 0) {
    return "No belief snapshot available.";
  }

  const conclusion = lines[0];
  const signalLines = lines
    .slice(1)
    .filter((line) => line.startsWith("- "))
    .map((line) => line.replace(/^- /, ""));
  const supporting = lines.slice(1).filter((line) => !line.startsWith("- "));

  return [
    `Conclusion: ${conclusion}`,
    signalLines.length > 0
      ? `Signals:\n- ${signalLines.join("\n- ")}`
      : "Signals: none listed",
    supporting.length > 0 ? `Limitations/notes: ${supporting.join(" ")}` : null,
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n\n");
}

function signalSnapshotForQuarter(
  points: SignalPoint[],
  quarter: string,
): SignalPoint[] {
  return points
    .filter((point) => point.quarter === quarter)
    .sort((a, b) => {
      const aScore = a.ror_ci_lower ?? -1;
      const bScore = b.ror_ci_lower ?? -1;
      if (a.signal_detected !== b.signal_detected) {
        return Number(b.signal_detected) - Number(a.signal_detected);
      }
      if (aScore !== bScore) {
        return bScore - aScore;
      }
      return b.report_count - a.report_count;
    });
}

function firstBeliefLine(belief: Belief | null): string | null {
  if (!belief) {
    return null;
  }
  const line = belief.answer_text
    .split("\n")
    .map((value) => value.trim())
    .find((value) => value.length > 0);
  return line ?? null;
}

export function Dashboard() {
  const navigate = useNavigate();
  const selectedDrugId = useVigilensStore((state) => state.selectedDrugId);
  const drugs = useVigilensStore((state) => state.drugs);
  const timelinePoints = useVigilensStore((state) => state.timelinePoints);
  const activeSignals = useVigilensStore((state) => state.activeSignals);
  const ingestStatus = useVigilensStore((state) => state.ingestStatus);
  const ingestProgress = useVigilensStore((state) => state.ingestProgress);
  const profile = useVigilensStore((state) => state.profile);
  const episodes = useVigilensStore((state) => state.episodes);
  const fdaActions = useVigilensStore((state) => state.fdaActions);
  const beliefs = useVigilensStore((state) => state.beliefs);
  const beliefDiff = useVigilensStore((state) => state.beliefDiff);
  const scorecard = useVigilensStore((state) => state.scorecard);
  const queryResponse = useVigilensStore((state) => state.queryResponse);
  const evidenceDrawerOpen = useVigilensStore(
    (state) => state.evidenceDrawerOpen,
  );
  const evidenceReportId = useVigilensStore((state) => state.evidenceReportId);

  const setSelectedDrugId = useVigilensStore(
    (state) => state.setSelectedDrugId,
  );
  const setDrugs = useVigilensStore((state) => state.setDrugs);
  const setIngestProgress = useVigilensStore(
    (state) => state.setIngestProgress,
  );
  const setIngestStatus = useVigilensStore((state) => state.setIngestStatus);
  const setTimelinePoints = useVigilensStore(
    (state) => state.setTimelinePoints,
  );
  const setActiveSignals = useVigilensStore((state) => state.setActiveSignals);
  const setProfile = useVigilensStore((state) => state.setProfile);
  const setEpisodes = useVigilensStore((state) => state.setEpisodes);
  const setFdaActions = useVigilensStore((state) => state.setFdaActions);
  const setBeliefs = useVigilensStore((state) => state.setBeliefs);
  const setBeliefDiff = useVigilensStore((state) => state.setBeliefDiff);
  const setScorecard = useVigilensStore((state) => state.setScorecard);
  const setQueryResponse = useVigilensStore((state) => state.setQueryResponse);
  const openEvidenceDrawer = useVigilensStore(
    (state) => state.openEvidenceDrawer,
  );
  const setEvidenceReport = useVigilensStore(
    (state) => state.setEvidenceReport,
  );
  const closeEvidenceDrawer = useVigilensStore(
    (state) => state.closeEvidenceDrawer,
  );

  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [viewedQuarter, setViewedQuarter] = useState<string | null>(null);
  const [playSpeedMs, setPlaySpeedMs] = useState(800);
  const [isPlaying, setIsPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [queryLoading, setQueryLoading] = useState(false);
  const [startDemoLoading, setStartDemoLoading] = useState(false);
  const [autoEvidenceResponse, setAutoEvidenceResponse] =
    useState<QueryResponse | null>(null);
  const [autoEvidenceLoading, setAutoEvidenceLoading] = useState(false);
  const [autoEvidenceError, setAutoEvidenceError] = useState<string | null>(
    null,
  );
  const [autoFocusEvent, setAutoFocusEvent] = useState<string | null>(null);
  const [autoReinterpretedReportIds, setAutoReinterpretedReportIds] = useState<
    string[]
  >([]);
  const [diffLoading, setDiffLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [casefileSummary, setCasefileSummary] =
    useState<CasefileSummary | null>(null);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [evermemosOk, setEvermemosOk] = useState<boolean | null>(null);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoStage, setDemoStage] = useState<DemoStage>("baseline");
  const [demoPresentationActive, setDemoPresentationActive] = useState(false);
  const [fastDemoReady, setFastDemoReady] = useState(false);
  const [forcedBeliefTab, setForcedBeliefTab] = useState<BeliefTabKey | null>(
    null,
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<
    "belief" | "episodic" | "query" | "all"
  >("query");
  const [showMemorySources, setShowMemorySources] = useState(false);
  const [signalToasts, setSignalToasts] = useState<SignalAlert[]>([]);
  const [agentRunState, setAgentRunState] = useState<AgentRunState>("idle");
  const [agentLog, setAgentLog] = useState<AgentThoughtLogEntry[]>([]);
  const [foresightStatus, setForesightStatus] =
    useState<ForesightMemoryStatus | null>(null);
  const [memoryViewerOpen, setMemoryViewerOpen] = useState(false);
  const [memoryViewerEntry, setMemoryViewerEntry] =
    useState<MemoryViewerEntry | null>(null);
  const [ingestAllProgress, setIngestAllProgress] = useState<{
    active: boolean;
    completedQuarters: number;
    totalQuarters: number | null;
  } | null>(null);
  const [reinterpretationMarkers, setReinterpretationMarkers] = useState<
    Array<{ quarter: string; reportId: string }>
  >([]);
  const [rebuildJob, setRebuildJob] = useState<TrackingJob | null>(null);
  const [activeRebuildJobId, setActiveRebuildJobId] = useState<string | null>(
    null,
  );
  const [rebuildJobLoading, setRebuildJobLoading] = useState(false);
  const [rebuildJobError, setRebuildJobError] = useState<string | null>(null);
  const [creatingRebuildJob, setCreatingRebuildJob] = useState(false);
  const [evidenceReportCache, setEvidenceReportCache] = useState<
    Record<string, FAERSReport>
  >({});
  const previousViewedQuarterRef = useRef<string | null>(null);
  const playbackAdvanceRef = useRef(false);
  const autoEvidenceAbortRef = useRef<AbortController | null>(null);
  const autoEvidenceRequestSeqRef = useRef(0);
  const autoEvidenceCacheRef = useRef<
    Map<string, { response: QueryResponse; reinterpretedReportIds: string[] }>
  >(new Map());
  const autoReinterpretCacheRef = useRef<Map<string, string[]>>(new Map());
  const beliefDiffCacheRef = useRef<Map<string, BeliefDiffResponse>>(
    new Map(),
  );
  const beliefDiffInFlightRef = useRef<Map<string, Promise<BeliefDiffResponse>>>(
    new Map(),
  );
  const casefileSummaryCacheRef = useRef<Map<string, CasefileSummary>>(
    new Map(),
  );
  const casefileSummaryInFlightRef = useRef<
    Map<string, Promise<CasefileSummary>>
  >(new Map());
  const casefileSummaryRequestSeqRef = useRef(0);
  const fetchDrugScopedSeqRef = useRef(0);
  const loadedQuarterSignatureRef = useRef<string>("");
  const demoRunTokenRef = useRef(0);
  const demoAbortRef = useRef<AbortController | null>(null);
  const thoughtQueueRef = useRef<AgentThoughtLogEntry[]>([]);
  const queuedThoughtIdsRef = useRef<Set<string>>(new Set());
  const thoughtPumpTimerRef = useRef<number | null>(null);
  const seenThoughtIdsRef = useRef<Set<string>>(new Set());
  const thoughtQuarterRef = useRef<string | null>(null);
  const lastSyntheticSummaryQuarterRef = useRef<string | null>(null);
  const lastSyntheticObservationQuarterRef = useRef<string | null>(null);
  const lastReinterpretToastRef = useRef<string | null>(null);
  const rebuildPollingInFlightRef = useRef(false);
  const rebuildReadyHandledRef = useRef<string | null>(null);
  const analystWorkspaceSectionRef = useRef<HTMLElement | null>(null);
  const analystWorkspaceScrollRequestedRef = useRef(false);

  useIngestProgressSocket(selectedDrugId);

  const loadedQuarters = ingestStatus?.quarters_loaded ?? [];
  const loadedQuarterSignature = useMemo(
    () => loadedQuarters.join("|"),
    [loadedQuarters],
  );
  const selectedDrug = useMemo(
    () => drugs.find((item) => item.id === selectedDrugId) ?? null,
    [drugs, selectedDrugId],
  );
  const clearThoughtTimers = useCallback(() => {
    if (thoughtPumpTimerRef.current !== null) {
      window.clearTimeout(thoughtPumpTimerRef.current);
      thoughtPumpTimerRef.current = null;
    }
    thoughtQueueRef.current = [];
    queuedThoughtIdsRef.current.clear();
  }, []);
  const pumpThoughtQueue = useCallback(() => {
    if (thoughtPumpTimerRef.current !== null) {
      return;
    }

    const flushNext = (): void => {
      const nextEntry = thoughtQueueRef.current.shift();
      if (!nextEntry) {
        thoughtPumpTimerRef.current = null;
        return;
      }

      queuedThoughtIdsRef.current.delete(nextEntry.id);
      seenThoughtIdsRef.current.add(nextEntry.id);
      setAgentLog((current) => [...current, nextEntry]);

      const delayMs = 100 + Math.floor(Math.random() * 101);
      thoughtPumpTimerRef.current = window.setTimeout(flushNext, delayMs);
    };

    thoughtPumpTimerRef.current = window.setTimeout(flushNext, 0);
  }, []);

  const ingestThoughtStreaming =
    ingestProgress?.phase === "starting" ||
    ingestProgress?.phase === "loading_reports" ||
    ingestProgress?.phase === "computing_signals" ||
    ingestProgress?.phase === "posting_evermemos" ||
    ingestProgress?.phase === "generating_beliefs";

  const appendSyntheticThought = useCallback(
    (entry: {
      id: string;
      type: AgentThoughtLogEntry["type"];
      content: string;
      quarter: string;
      source: "quarter_summary" | "time_travel";
    }) => {
      const timestamp = new Date().toISOString();
      const nextEntry: AgentThoughtLogEntry = {
        id: entry.id,
        type: entry.type,
        content: entry.content,
        timestamp,
        origin: "narrative",
        metadata: {
          synthetic: true,
          quarter: entry.quarter,
          source: entry.source,
        },
      };
      setAgentLog((current) => {
        if (current.some((item) => item.id === entry.id)) {
          return current;
        }
        return [...current, nextEntry];
      });
    },
    [],
  );

  const appendQueryThoughts = useCallback(
    (params: {
      quarter: string;
      question: string;
      response: QueryResponse;
      source: "manual" | "auto";
    }) => {
      const now = new Date();
      const memoryRefs = params.response.episodic_context
        .map((item) => item.memory_id ?? null)
        .filter(
          (value): value is string =>
            typeof value === "string" && value.trim().length > 0,
        );
      const episodicCount = params.response.episodic_context.length;
      const foresightRefs = (params.response.foresight_memory_ids ?? []).filter(
        (value): value is string =>
          typeof value === "string" && value.trim().length > 0,
      );
      const idPrefix = [
        "synthetic",
        "query",
        params.source,
        selectedDrugId,
        params.quarter,
        params.response.belief_id,
        String(now.getTime()),
      ].join(":");
      const entries: AgentThoughtLogEntry[] = [
        {
          id: `${idPrefix}:search`,
          type: "memory_query",
          content: buildQuerySearchThought(params.question),
          timestamp: now.toISOString(),
          origin: "narrative",
        },
        {
          id: `${idPrefix}:grounding`,
          type: "memory_recall",
          content: buildQueryEpisodicRecallThought(episodicCount),
          timestamp: new Date(now.getTime() + 1).toISOString(),
          origin: "narrative",
          memoryRefs:
            memoryRefs.length > 0 ? memoryRefs.slice(0, 5) : undefined,
        },
        {
          id: `${idPrefix}:foresight`,
          type: "foresight",
          content: buildQueryForesightRecallThought(foresightRefs.length),
          timestamp: new Date(now.getTime() + 2).toISOString(),
          origin: "narrative",
          memoryRefs:
            foresightRefs.length > 0 ? foresightRefs.slice(0, 5) : undefined,
        },
        {
          id: `${idPrefix}:belief`,
          type: "reasoning",
          content: buildQueryBeliefThought(
            params.quarter,
            params.response.answer_text,
          ),
          timestamp: new Date(now.getTime() + 3).toISOString(),
          origin: "narrative",
        },
      ];

      setAgentLog((current) => [...current, ...entries]);
    },
    [selectedDrugId],
  );

  const clearAutoEvidenceCaches = useCallback(() => {
    autoEvidenceAbortRef.current?.abort();
    autoEvidenceAbortRef.current = null;
    autoEvidenceRequestSeqRef.current += 1;
    autoEvidenceCacheRef.current.clear();
    autoReinterpretCacheRef.current.clear();
    setAutoEvidenceResponse(null);
    setAutoEvidenceLoading(false);
    setAutoEvidenceError(null);
    setAutoFocusEvent(null);
    setAutoReinterpretedReportIds([]);
  }, []);

  const buildBeliefDiffCacheKey = useCallback(
    (beforeId: string, afterId: string) =>
      `${selectedDrugId}|${beforeId}|${afterId}`,
    [selectedDrugId],
  );

  const buildCasefileSummaryCacheKey = useCallback(
    (quarter?: string | null) => `${selectedDrugId}|${quarter ?? "__latest__"}`,
    [selectedDrugId],
  );

  const clearTimeTravelCaches = useCallback(() => {
    clearCachedResource(
      beliefDiffCacheRef.current,
      beliefDiffInFlightRef.current,
    );
    clearCachedResource(
      casefileSummaryCacheRef.current,
      casefileSummaryInFlightRef.current,
    );
  }, []);

  const cacheCasefileSummary = useCallback(
    (summary: CasefileSummary, includeLatestAlias = false) => {
      seedCachedResource(
        buildCasefileSummaryCacheKey(summary.viewed_quarter),
        casefileSummaryCacheRef.current,
        summary,
      );
      if (includeLatestAlias) {
        seedCachedResource(
          buildCasefileSummaryCacheKey(),
          casefileSummaryCacheRef.current,
          summary,
        );
      }
    },
    [buildCasefileSummaryCacheKey],
  );

  const loadBeliefDiffCached = useCallback(
    (beforeId: string, afterId: string) =>
      getCachedResource(
        buildBeliefDiffCacheKey(beforeId, afterId),
        beliefDiffCacheRef.current,
        beliefDiffInFlightRef.current,
        () => getBeliefDiff(selectedDrugId, beforeId, afterId),
      ),
    [buildBeliefDiffCacheKey, selectedDrugId],
  );

  const loadCasefileSummaryCached = useCallback(
    (quarter?: string | null) =>
      getCachedResource(
        buildCasefileSummaryCacheKey(quarter),
        casefileSummaryCacheRef.current,
        casefileSummaryInFlightRef.current,
        () => getCasefileSummary(selectedDrugId, quarter ?? undefined),
      ).then((summary) => {
        cacheCasefileSummary(summary, !quarter);
        return summary;
      }),
    [buildCasefileSummaryCacheKey, cacheCasefileSummary, selectedDrugId],
  );

  const cacheEvidenceReports = useCallback((reports: FAERSReport[]) => {
    if (reports.length === 0) {
      return;
    }

    setEvidenceReportCache((current) => {
      let next = current;
      for (const report of reports) {
        if (current[report.safetyreportid] === report) {
          continue;
        }
        if (next === current) {
          next = { ...current };
        }
        next[report.safetyreportid] = report;
      }
      return next;
    });
  }, []);

  const handleEvidenceDrawerLoaded = useCallback(
    (report: FAERSReport | null) => {
      setEvidenceReport(report);
      if (report) {
        cacheEvidenceReports([report]);
      }
    },
    [cacheEvidenceReports, setEvidenceReport],
  );

  const resetCasefileRunState = useCallback(() => {
    setBeliefDiff(null);
    clearTimeTravelCaches();
    setQueryResponse(null);
    clearAutoEvidenceCaches();
    setEvidenceReportCache({});
    setReinterpretationMarkers([]);
    setSignalToasts([]);
    clearThoughtTimers();
    seenThoughtIdsRef.current.clear();
    thoughtQuarterRef.current = null;
    lastSyntheticSummaryQuarterRef.current = null;
    lastSyntheticObservationQuarterRef.current = null;
    setAgentLog([]);
    setAgentRunState("idle");
    setDemoStage("baseline");
    setDemoPresentationActive(false);
    setFastDemoReady(false);
    setShowMemorySources(false);
    setForcedBeliefTab(null);
    setAutoEvidenceResponse(null);
    setAutoEvidenceLoading(false);
    setAutoEvidenceError(null);
    setAutoFocusEvent(null);
    setAutoReinterpretedReportIds([]);
    setDemoRunning(false);
    setDrawerOpen(false);
    setMemoryViewerOpen(false);
    setMemoryViewerEntry(null);
    setIngestAllProgress(null);
    setIsPlaying(false);
  }, [clearAutoEvidenceCaches, clearThoughtTimers, clearTimeTravelCaches]);

  const cancelDemoRun = useCallback(() => {
    demoRunTokenRef.current += 1;
    demoAbortRef.current?.abort();
    demoAbortRef.current = null;
    clearThoughtTimers();
    setDemoRunning(false);
    setAgentRunState("cancelled");
  }, [clearThoughtTimers]);

  const isPrimaryDemoDrug =
    selectedDrugId === "semaglutide" && demoPresentationActive;
  const isSemaglutideScorecardDrug = selectedDrugId === "semaglutide";
  const analystWorkspaceOpen = demoStage === "analyst";

  const quarterOrder = useMemo(() => {
    return new Map(loadedQuarters.map((quarter, index) => [quarter, index]));
  }, [loadedQuarters]);

  const viewedQuarterIndex = useMemo(() => {
    if (!viewedQuarter) {
      return loadedQuarters.length > 0 ? loadedQuarters.length - 1 : -1;
    }
    return quarterOrder.get(viewedQuarter) ?? -1;
  }, [loadedQuarters.length, quarterOrder, viewedQuarter]);

  const latestLoadedQuarter = ingestStatus?.quarters_loaded.at(-1) ?? null;
  const totalReportsLoadedDisplay =
    ingestStatus?.total_reports_loaded ?? selectedDrug?.total_reports ?? 0;
  const quartersLoadedCountDisplay =
    loadedQuarters.length > 0
      ? loadedQuarters.length
      : (selectedDrug?.quarters_loaded.length ?? 0);
  const showFirstLoadEntrypoint = loadedQuarters.length === 0;
  const canStartFromEntrypoint = Boolean(ingestStatus?.next_quarter);
  const activeQuarter = viewedQuarter ?? latestLoadedQuarter;
  const chartQuarterLabel = activeQuarter ?? "-";
  const scorecardPresentationMode = isSemaglutideScorecardDrug
    ? "demo"
    : "generic";
  const metricsScorecardProjectionQuarter =
    demoStage === "validation" || demoStage === "analyst"
      ? activeQuarter === latestLoadedQuarter
        ? null
        : activeQuarter
      : activeQuarter;
  const scorecardPinnedToLatestForDemo = isSemaglutideScorecardDrug;
  const scorecardProjectionQuarter =
    scorecardPinnedToLatestForDemo
      ? null
      : metricsScorecardProjectionQuarter;
  const metricsScorecardAsOfViewed = useMemo(
    () =>
      projectScorecardAsOf(
        scorecard,
        metricsScorecardProjectionQuarter,
        latestLoadedQuarter,
      ),
    [latestLoadedQuarter, metricsScorecardProjectionQuarter, scorecard],
  );
  const scorecardAsOfViewed = useMemo(
    () =>
      projectScorecardAsOf(
        scorecard,
        scorecardProjectionQuarter,
        latestLoadedQuarter,
      ),
    [latestLoadedQuarter, scorecard, scorecardProjectionQuarter],
  );
  const hiddenFuturePredictionsCount = useMemo(() => {
    if (!activeQuarter) {
      return 0;
    }
    return Math.max(0, scorecard.length - scorecardAsOfViewed.length);
  }, [activeQuarter, scorecard.length, scorecardAsOfViewed.length]);
  const displayedScorecard = scorecardPinnedToLatestForDemo
    ? scorecard
    : scorecardAsOfViewed;
  const displayedHiddenFuturePredictionsCount = scorecardPinnedToLatestForDemo
    ? 0
    : hiddenFuturePredictionsCount;
  const scorecardQuarterLabel = scorecardPinnedToLatestForDemo
    ? null
    : activeQuarter;
  const visibleScorecard = useMemo(
    () =>
      splitScorecardEntries(scorecard, scorecardPresentationMode).activeEntries,
    [scorecard, scorecardPresentationMode],
  );
  const visibleScorecardAsOfViewed = useMemo(
    () =>
      splitScorecardEntries(scorecardAsOfViewed, scorecardPresentationMode)
        .activeEntries,
    [scorecardAsOfViewed, scorecardPresentationMode],
  );
  const visibleMetricsScorecardAsOfViewed = useMemo(
    () =>
      splitScorecardEntries(
        metricsScorecardAsOfViewed,
        scorecardPresentationMode,
      ).activeEntries,
    [metricsScorecardAsOfViewed, scorecardPresentationMode],
  );

  useEffect(() => {
    if (!analystWorkspaceOpen || !analystWorkspaceScrollRequestedRef.current) {
      return;
    }
    analystWorkspaceScrollRequestedRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      analystWorkspaceSectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [analystWorkspaceOpen]);

  const timelineAsOfViewed = useMemo(() => {
    if (viewedQuarterIndex < 0) {
      return [];
    }
    return timelinePoints.filter((point) => {
      const idx = quarterOrder.get(point.quarter);
      return idx !== undefined && idx <= viewedQuarterIndex;
    });
  }, [quarterOrder, timelinePoints, viewedQuarterIndex]);

  const signalSnapshot = useMemo(() => {
    if (!viewedQuarter) {
      return [];
    }
    return signalSnapshotForQuarter(timelinePoints, viewedQuarter);
  }, [timelinePoints, viewedQuarter]);

  const topSignal = useMemo(() => {
    if (signalSnapshot.length === 0) {
      return null;
    }
    return [...signalSnapshot].sort((a, b) => {
      const aRor = a.ror ?? -1;
      const bRor = b.ror ?? -1;
      if (a.signal_detected !== b.signal_detected) {
        return Number(b.signal_detected) - Number(a.signal_detected);
      }
      if (aRor !== bRor) {
        return bRor - aRor;
      }
      return b.report_count - a.report_count;
    })[0];
  }, [signalSnapshot]);

  const scorecardSummary = useMemo(() => {
    const validated = scorecard.filter(
      (entry) => entry.result === "validated",
    ).length;
    const pending = scorecard.filter(
      (entry) => entry.result === "pending",
    ).length;
    return `${validated} validated and ${pending} pending receipts`;
  }, [scorecard]);
  const memoryStatus = useMemo((): {
    label: string;
    tone: MemoryStatusTone;
  } => {
    if (evermemosOk === false || foresightStatus?.status === "warning") {
      return { label: "Memory degraded", tone: "warning" };
    }
    if (evermemosOk === true) {
      return { label: "Memory-backed", tone: "ok" };
    }
    return { label: "Memory status pending", tone: "idle" };
  }, [evermemosOk, foresightStatus?.status]);

  const beliefsCurrentQuarter = useMemo(() => {
    if (!viewedQuarter) {
      return [];
    }
    return pickLatestBeliefPerQuestion(
      beliefs.filter((belief) => belief.quarter_context === viewedQuarter),
    );
  }, [beliefs, viewedQuarter]);

  const metricsAsOf = useMemo(() => {
    const currentScorecardCounts = countScorecardEntries(visibleScorecard);
    const viewedScorecardCounts = countScorecardEntries(
      visibleMetricsScorecardAsOfViewed,
    );

    if (!viewedQuarter || viewedQuarter === latestLoadedQuarter) {
      return {
        totalReports: totalReportsLoadedDisplay,
        activeSignals: activeSignals.length,
        beliefsTracked: beliefs.length,
        predictionsValidated: currentScorecardCounts.validated,
        predictionsPending: currentScorecardCounts.pending,
        predictionsEarly: currentScorecardCounts.early,
        predictionsTotal: currentScorecardCounts.total,
        quartersLoaded: quartersLoadedCountDisplay,
      };
    }
    const quarterSignals = signalSnapshot;
    const drugTotal =
      quarterSignals.length > 0
        ? Math.max(...quarterSignals.map((s) => s.drug_total_cumulative))
        : 0;
    const detectedCount = quarterSignals.filter(
      (s) => s.signal_detected,
    ).length;

    return {
      totalReports: drugTotal || totalReportsLoadedDisplay,
      activeSignals: detectedCount,
      beliefsTracked: beliefsCurrentQuarter.length,
      predictionsValidated: viewedScorecardCounts.validated,
      predictionsPending: viewedScorecardCounts.pending,
      predictionsEarly: viewedScorecardCounts.early,
      predictionsTotal: viewedScorecardCounts.total,
      quartersLoaded: viewedQuarterIndex + 1,
    };
  }, [
    viewedQuarter,
    latestLoadedQuarter,
    totalReportsLoadedDisplay,
    activeSignals.length,
    beliefs.length,
    visibleScorecard,
    signalSnapshot,
    beliefsCurrentQuarter.length,
    visibleMetricsScorecardAsOfViewed,
    viewedQuarterIndex,
    quartersLoadedCountDisplay,
  ]);

  const latestProofBackedSignals = useMemo(() => {
    return (
      casefileSummary?.proof_backed_signals ??
      casefileSummary?.public_forecasts?.filter(
        (item) => item.track === "proof",
      ).length ??
      0
    );
  }, [casefileSummary]);

  const predictionMetric = useMemo(() => {
    if (
      !isSemaglutideScorecardDrug &&
      latestProofBackedSignals > 0 &&
      metricsAsOf.predictionsValidated === 0
    ) {
      return {
        label: "Proof-backed Signals",
        value: latestProofBackedSignals,
        suffix: null,
      };
    }
    if (isSemaglutideScorecardDrug) {
      return {
        label: "Receipt Forecasts",
        value: metricsAsOf.predictionsValidated,
        suffix: buildDemoReceiptMetricSuffix({
          pending: metricsAsOf.predictionsPending,
          early: metricsAsOf.predictionsEarly,
        }),
      };
    }
    return {
      label: "Receipt Forecasts",
      value: metricsAsOf.predictionsValidated,
      suffix: `/ ${metricsAsOf.predictionsTotal}`,
    };
  }, [
    isSemaglutideScorecardDrug,
    latestProofBackedSignals,
    metricsAsOf.predictionsEarly,
    metricsAsOf.predictionsPending,
    metricsAsOf.predictionsValidated,
    metricsAsOf.predictionsTotal,
  ]);

  useEffect(() => {
    if (!selectedDrugId || !activeQuarter) {
      return;
    }
    if (
      casefileSummary?.drug_id === selectedDrugId &&
      casefileSummary.viewed_quarter === activeQuarter
    ) {
      return;
    }
    const requestSeq = casefileSummaryRequestSeqRef.current + 1;
    casefileSummaryRequestSeqRef.current = requestSeq;
    const cacheKey = buildCasefileSummaryCacheKey(activeQuarter);
    const cached = casefileSummaryCacheRef.current.get(cacheKey);
    if (cached) {
      setCasefileSummary(cached);
      return;
    }

    let cancelled = false;
    void loadCasefileSummaryCached(activeQuarter)
      .then((value) => {
        if (!cancelled && requestSeq === casefileSummaryRequestSeqRef.current) {
          setCasefileSummary(value);
        }
      })
      .catch(() => {
        // Best-effort time-travel casefile summary; preserve the latest snapshot on failure.
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeQuarter,
    buildCasefileSummaryCacheKey,
    casefileSummary?.drug_id,
    casefileSummary?.viewed_quarter,
    loadCasefileSummaryCached,
    selectedDrugId,
  ]);

  const beliefsPreviousQuarter = useMemo(() => {
    if (!viewedQuarter) {
      return [];
    }
    const idx = loadedQuarters.indexOf(viewedQuarter);
    if (idx <= 0) {
      return [];
    }
    const previous = loadedQuarters[idx - 1];
    return pickLatestBeliefPerQuestion(
      beliefs.filter((belief) => belief.quarter_context === previous),
    );
  }, [beliefs, loadedQuarters, viewedQuarter]);

  const loopTraceSteps = useMemo(() => {
    const entriesForQuarter = activeQuarter
      ? agentLog.filter((entry) => {
          const quarter = entry.metadata?.quarter;
          return typeof quarter !== "string" || quarter === activeQuarter;
        })
      : agentLog;

    const latestOfType = (types: AgentThoughtLogEntry["type"][]) =>
      [...entriesForQuarter]
        .reverse()
        .find((entry) => types.includes(entry.type));

    const memoryEntry =
      latestOfType([
        "memory_query",
        "memory_recall",
        "memory_write",
        "foresight",
      ]) ?? null;
    const reasoningEntry =
      latestOfType(["reasoning", "reinterpretation"]) ?? null;
    const actionEntry =
      latestOfType(["action", "foresight", "reinterpretation"]) ?? null;
    const topBelief = beliefsCurrentQuarter[0] ?? null;
    const episodeForQuarter = activeQuarter
      ? (episodes.find((episode) => episode.quarter === activeQuarter) ?? null)
      : null;
    const validatedCount = scorecardAsOfViewed.filter(
      (entry) => entry.result === "validated",
    ).length;
    const pendingCount = scorecardAsOfViewed.filter(
      (entry) => entry.result === "pending",
    ).length;
    const topSignalLabel =
      signalSnapshot.length > 0
        ? `${signalSnapshot[0].adverse_event} ROR ${signalSnapshot[0].ror?.toFixed(2) ?? "n/a"}`
        : "No active signal snapshot";
    const episodicSummary =
      episodeForQuarter?.narrative?.trim() ||
      (activeQuarter
        ? `Quarter ${activeQuarter} loaded with ${signalSnapshot.length} tracked signal rows.`
        : "No quarter selected.");
    const reasoningSummary =
      firstBeliefLine(topBelief) ||
      (beliefDiff?.reinterpreted_report_ids.length
        ? `${beliefDiff.reinterpreted_report_ids.length} earlier reports changed meaning in this comparison window.`
        : `Current quarter focus: ${topSignalLabel}.`);
    const actionSummary =
      scorecardAsOfViewed.length > 0
        ? `Scorecard now tracks ${validatedCount} validated and ${pendingCount} pending receipt${
            validatedCount + pendingCount === 1 ? "" : "s"
          }.`
        : "No scorecard receipts yet; the agent is still establishing a regulatory horizon.";

    return {
      memory: memoryEntry?.content ?? episodicSummary,
      reasoning: reasoningEntry?.content ?? reasoningSummary,
      action: actionEntry?.content ?? actionSummary,
    };
  }, [
    activeQuarter,
    agentLog,
    beliefDiff,
    beliefsCurrentQuarter,
    episodes,
    scorecardAsOfViewed,
    signalSnapshot,
  ]);

  useEffect(() => {
    if (!activeQuarter || beliefs.length === 0 || loadedQuarters.length === 0) {
      setBeliefDiff(null);
      setDiffLoading(false);
      return;
    }

    const pair = pickBeliefPairForQuarterDiff({
      beliefs,
      activeQuarter,
      loadedQuarters,
    });
    if (!pair) {
      setBeliefDiff(null);
      setDiffLoading(false);
      return;
    }

    const cacheKey = buildBeliefDiffCacheKey(pair.beforeId, pair.afterId);
    const cached = beliefDiffCacheRef.current.get(cacheKey);
    if (cached) {
      setBeliefDiff(cached);
      setDiffLoading(false);
      return;
    }

    let cancelled = false;
    setDiffLoading(true);
    void loadBeliefDiffCached(pair.beforeId, pair.afterId)
      .then((diff) => {
        if (cancelled) {
          return;
        }
        setBeliefDiff(diff);
      })
      .catch(() => {
        if (!cancelled) {
          // Ignore; BeliefDiff drawer still supports manual fetch attempts.
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDiffLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeQuarter,
    beliefs,
    buildBeliefDiffCacheKey,
    loadBeliefDiffCached,
    loadedQuarters,
    setBeliefDiff,
  ]);

  const profileMemoryId = useMemo(() => {
    return buildProfileMemoryId(selectedDrugId, activeQuarter);
  }, [activeQuarter, selectedDrugId]);

  const currentEpisode = useMemo(() => {
    if (!activeQuarter) {
      return null;
    }
    return (
      episodes.find((episode) => episode.quarter === activeQuarter) ?? null
    );
  }, [activeQuarter, episodes]);

  const highlightBeliefRevision =
    Boolean(activeQuarter) &&
    Boolean(beliefDiff?.triggered_by_quarter) &&
    activeQuarter === beliefDiff?.triggered_by_quarter &&
    (beliefDiff?.reinterpreted_report_ids.length ?? 0) > 0;

  const keyReceipt = useMemo(
    () =>
      scorecardAsOfViewed.find(
        (entry) => entry.prediction.adverse_event === "Ileus",
      ) ??
      scorecardAsOfViewed.find((entry) => entry.result === "validated") ??
      scorecardAsOfViewed[0] ??
      null,
    [scorecardAsOfViewed],
  );
  const secondaryReceiptCount = useMemo(() => {
    if (!keyReceipt) {
      return 0;
    }
    return scorecardAsOfViewed.filter(
      (entry) => entry.prediction.id !== keyReceipt.prediction.id,
    ).length;
  }, [keyReceipt, scorecardAsOfViewed]);

  const episodicMemoryById = useMemo(() => {
    const map = new Map<string, EpisodicSummary>();
    const addEpisode = (episode: EpisodicSummary) => {
      const candidateIds = [
        episode.memory_id,
        `episodic:${selectedDrugId}:${episode.quarter}`,
      ].filter((value): value is string => Boolean(value));
      for (const memoryId of candidateIds) {
        if (!map.has(memoryId)) {
          map.set(memoryId, episode);
        }
      }
    };
    for (const episode of episodes) {
      addEpisode(episode);
    }
    for (const episode of autoEvidenceResponse?.episodic_context ?? []) {
      addEpisode(episode);
    }
    for (const episode of queryResponse?.episodic_context ?? []) {
      addEpisode(episode);
    }
    return map;
  }, [
    autoEvidenceResponse?.episodic_context,
    episodes,
    queryResponse?.episodic_context,
    selectedDrugId,
  ]);

  const beliefRevisionMemoryIds = useMemo(() => {
    if (!beliefDiff) {
      return [];
    }

    const collected: string[] = [];
    const addMemoryId = (memoryId: string | null | undefined) => {
      if (!memoryId || collected.includes(memoryId)) {
        return;
      }
      collected.push(memoryId);
    };
    const addEpisodeMemory = (quarter: string) => {
      const episode = episodes.find((item) => item.quarter === quarter);
      if (!episode) {
        return;
      }
      addMemoryId(episode.memory_id ?? `episodic:${selectedDrugId}:${quarter}`);
    };

    for (const memoryId of beliefDiff.after.episodic_ids_used) {
      addMemoryId(memoryId);
    }
    for (const memoryId of beliefDiff.before.episodic_ids_used) {
      addMemoryId(memoryId);
    }
    addEpisodeMemory(beliefDiff.after.quarter_context);
    addEpisodeMemory(beliefDiff.before.quarter_context);

    return collected.slice(0, 4);
  }, [beliefDiff, episodes, selectedDrugId]);

  const openMemoryViewer = useCallback((entry: MemoryViewerEntry) => {
    setMemoryViewerEntry(entry);
    setMemoryViewerOpen(true);
  }, []);

  const closeMemoryViewer = useCallback(() => {
    setMemoryViewerOpen(false);
    setMemoryViewerEntry(null);
  }, []);

  const openEpisodicMemoryFromBelief = useCallback(
    (memoryId: string, belief: Belief) => {
      const episode = episodicMemoryById.get(memoryId);
      const memoryQuarter = episode?.quarter ?? belief.quarter_context;
      const label = `Episodic Memory - ${selectedDrugId}, ${memoryQuarter ?? "-"}`;
      openMemoryViewer({
        id: memoryId,
        type: "Episodic",
        label,
        quarter: memoryQuarter,
        narrative:
          episode?.narrative ?? formatBeliefSnapshot(belief.answer_text),
        source:
          episode?.memory_source === "postgres_fallback"
            ? "Postgres fallback episodic memory"
            : "EverMemOS Episodic memory",
        whyUsed: `This memory was recalled when the agent answered: "${belief.question_text}"`,
        metadata: [
          {
            label: "Belief confidence",
            value: String(belief.confidence_score),
          },
          {
            label: "Signals in memory",
            value:
              episode && episode.key_signals_mentioned.length > 0
                ? episode.key_signals_mentioned.join(", ")
                : "-",
          },
        ],
      });
    },
    [episodicMemoryById, openMemoryViewer, selectedDrugId],
  );

  const openEpisodicTimelineMemory = useCallback(
    (episode: EpisodicSummary) => {
      const memoryId =
        episode.memory_id ?? `episodic:${selectedDrugId}:${episode.quarter}`;
      openMemoryViewer({
        id: memoryId,
        type: "Episodic",
        label: `Episodic Memory - ${selectedDrugId}, ${episode.quarter}`,
        quarter: episode.quarter,
        narrative: episode.narrative,
        source:
          episode.memory_source === "postgres_fallback"
            ? "Postgres fallback episodic memory"
            : "EverMemOS Episodic memory",
        whyUsed: `This memory was used to reconstruct the agent's quarterly reasoning timeline for ${episode.quarter}.`,
        metadata: [
          {
            label: "Reports ingested",
            value: String(episode.report_count_ingested),
          },
          {
            label: "Key signals",
            value:
              episode.key_signals_mentioned.length > 0
                ? episode.key_signals_mentioned.join(", ")
                : "none",
          },
        ],
      });
    },
    [openMemoryViewer, selectedDrugId],
  );

  const openProfileMemory = useCallback(() => {
    if (!profile) {
      return;
    }
    openMemoryViewer({
      id: profileMemoryId,
      type: "Profile",
      label: `Profile Memory - ${selectedDrugId}, ${activeQuarter ?? "-"}`,
      quarter: activeQuarter,
      narrative: [
        `Assessment: ${profile.current_assessment}`,
        `Known signals: ${profile.known_signals.join(", ") || "none"}`,
        `Investigating: ${profile.investigating_signals.join(", ") || "none"}`,
        `Risk level: ${profile.risk_level}`,
      ].join("\n"),
      source: "EverMemOS Profile memory",
      whyUsed:
        "This memory was recalled to generate the sidebar drug assessment summary.",
      metadata: [{ label: "Drug", value: profile.drug_id }],
    });
  }, [
    activeQuarter,
    openMemoryViewer,
    profile,
    profileMemoryId,
    selectedDrugId,
  ]);

  const openEventLogMemory = useCallback(
    (memoryId: string, report: FAERSReport) => {
      const resolvedMemoryId =
        report.eventlog_memory_id ??
        memoryId ??
        buildEventLogMemoryId(selectedDrugId, report.safetyreportid);
      openMemoryViewer({
        id: resolvedMemoryId,
        type: "EventLog",
        label: `EventLog Memory - Report ${report.safetyreportid}`,
        quarter: activeQuarter,
        narrative: [
          `EventLog retrieval for report ${report.safetyreportid}.`,
          `Reactions: ${report.reactions.join(", ") || "none"}.`,
          `Seriousness: ${report.serious ? "serious" : "non-serious"}.`,
          report.outcomes.length > 0
            ? `Outcomes: ${report.outcomes.join(", ")}.`
            : "Outcomes: none.",
        ].join("\n"),
        source: "EverMemOS EventLog search",
        whyUsed:
          "This memory was used to ground the Evidence Spotlight card with a concrete patient report.",
        metadata: [{ label: "Received date", value: report.receivedate }],
      });
    },
    [activeQuarter, openMemoryViewer, selectedDrugId],
  );

  const openForesightMemory = useCallback(
    (entry: ScorecardEntry, memoryId: string) => {
      const prediction = entry.prediction;
      openMemoryViewer({
        id: memoryId,
        type: "Foresight",
        label: `Foresight Memory - ${prediction.adverse_event}, ${prediction.created_at_quarter}`,
        quarter: prediction.created_at_quarter,
        narrative: [
          `Prediction: ${prediction.adverse_event} ${prediction.predicted_action}`,
          `Confidence: ${prediction.confidence}`,
          `Time range: ${prediction.predicted_date_range[0]} to ${prediction.predicted_date_range[1]}`,
          `Created at quarter: ${prediction.created_at_quarter}`,
          `Basis: ${prediction.basis.summary}`,
          `Prediction scope: ${prediction.scope.label}`,
          `Supporting event: ${prediction.supporting_event.adverse_event} (${prediction.supporting_event.quarter})`,
        ].join("\n"),
        source: "EverMemOS Foresight memory",
        whyUsed:
          "This memory was recalled to explain how a scorecard forecast was generated before the FDA action.",
        metadata: [
          { label: "Validation result", value: entry.result.toUpperCase() },
          {
            label: "Prediction basis",
            value: prediction.basis.type.replaceAll("_", " "),
          },
          { label: "Prediction scope", value: prediction.scope.label },
          {
            label: "Actual action scope",
            value: entry.actual_fda_action?.scope.label ?? "Awaiting action",
          },
          {
            label: "FDA action",
            value: entry.actual_fda_action
              ? entry.actual_fda_action.title
              : "Awaiting action",
          },
        ],
      });
    },
    [openMemoryViewer],
  );

  const openThoughtMemoryRef = useCallback(
    (memoryId: string, entry: AgentThoughtLogEntry) => {
      const previewContainer = entry.metadata?.memory_preview;
      let previewText = "";
      if (previewContainer && typeof previewContainer === "object") {
        const candidate = (previewContainer as Record<string, unknown>)[
          memoryId
        ];
        if (typeof candidate === "string") {
          previewText = candidate;
        }
      }

      const quarterFromMeta =
        typeof entry.metadata?.quarter === "string"
          ? entry.metadata.quarter
          : activeQuarter;
      const memoryType = memoryTypeFromId(memoryId, entry.type);
      openMemoryViewer({
        id: memoryId,
        type: memoryType,
        label: `${memoryType} Memory - ${quarterFromMeta ?? "-"}`,
        quarter: quarterFromMeta,
        narrative:
          previewText ||
          `Referenced from ${entry.type.toUpperCase()} thought: ${entry.content}`,
        source: "Agent thought stream reference",
        whyUsed: `This memory was referenced during a ${entry.type.toUpperCase()} thought in the live agent activity stream.`,
        metadata: [
          { label: "Thought type", value: entry.type.toUpperCase() },
          { label: "Logged at", value: entry.timestamp },
        ],
      });
    },
    [activeQuarter, openMemoryViewer],
  );

  const fetchGlobal = useCallback(async () => {
    const [healthRes, drugsRes] = await Promise.allSettled([
      getHealth(),
      getDrugs(),
    ]);
    if (healthRes.status === "fulfilled") {
      setHealthOk(Boolean(healthRes.value.ok && healthRes.value.postgres_ok));
      setEvermemosOk(Boolean(healthRes.value.evermemos_ok));
    } else {
      setHealthOk(null);
      setEvermemosOk(null);
    }
    if (drugsRes.status === "fulfilled") {
      setDrugs(drugsRes.value);
      if (
        !drugsRes.value.find((item) => item.id === selectedDrugId) &&
        drugsRes.value.length > 0
      ) {
        setSelectedDrugId(drugsRes.value[0].id);
      }
    }
  }, [selectedDrugId, setDrugs, setSelectedDrugId]);

  const fetchDrugScoped = useCallback(async () => {
    const requestSeq = fetchDrugScopedSeqRef.current + 1;
    fetchDrugScopedSeqRef.current = requestSeq;
    const isCurrentRequest = () => fetchDrugScopedSeqRef.current === requestSeq;

    setLoading(true);
    setError(null);
    setForesightStatus(null);

    const statusPromise = getIngestStatus(selectedDrugId);
    void statusPromise
      .then((status) => {
        if (isCurrentRequest()) {
          setIngestStatus(status);
        }
      })
      .catch(() => {
        // Error handling is centralized after Promise.allSettled below.
      });

    // Ancillary endpoints can be slower (EverMemOS lookups / status scans).
    // Fire them in background so core graph+scorecard rendering is not blocked.
    void getProfile(selectedDrugId)
      .then((value) => {
        if (isCurrentRequest()) {
          setProfile(value);
        }
      })
      .catch(() => {
        // Best-effort enrichment; keep existing profile on failure.
      });
    void getEpisodes(selectedDrugId)
      .then((value) => {
        if (isCurrentRequest()) {
          setEpisodes(value);
        }
      })
      .catch(() => {
        // Best-effort enrichment; keep fallback/previous episodes.
      });
    void getForesightStatus(selectedDrugId)
      .then((value) => {
        if (isCurrentRequest()) {
          setForesightStatus(value);
        }
      })
      .catch(() => {
        // Best-effort status; UI degrades gracefully when unavailable.
      });

    const [
      statusRes,
      timelineRes,
      signalsRes,
      actionsRes,
      beliefsRes,
      scorecardRes,
      casefileSummaryRes,
    ] = await Promise.allSettled([
      statusPromise,
      getTimeline(selectedDrugId),
      getSignals(selectedDrugId),
      getFdaActions(selectedDrugId),
      getBeliefs(selectedDrugId),
      getScorecard(selectedDrugId),
      loadCasefileSummaryCached(),
    ]);

    if (!isCurrentRequest()) {
      return;
    }

    if (statusRes.status === "fulfilled") {
      setIngestStatus(statusRes.value);
    }
    if (timelineRes.status === "fulfilled") {
      setTimelinePoints(timelineRes.value);
    }
    if (signalsRes.status === "fulfilled") {
      setActiveSignals(signalsRes.value);
      if (signalsRes.value.length > 0) {
        setSelectedEvents(
          signalsRes.value
            .slice(0, MAX_TRAJECTORY_EVENTS)
            .map((item) => item.adverse_event),
        );
      }
    }
    if (actionsRes.status === "fulfilled") {
      setFdaActions(actionsRes.value);
    }
    if (beliefsRes.status === "fulfilled") {
      setBeliefs(beliefsRes.value);
    }
    if (scorecardRes.status === "fulfilled") {
      setScorecard(scorecardRes.value);
    }
    if (casefileSummaryRes.status === "fulfilled") {
      setCasefileSummary(casefileSummaryRes.value);
    }

    const failures = [
      statusRes,
      timelineRes,
      signalsRes,
      actionsRes,
      beliefsRes,
      scorecardRes,
      casefileSummaryRes,
    ].filter((item) => item.status === "rejected");
    if (
      failures.length > 0 &&
      statusRes.status === "rejected" &&
      timelineRes.status === "rejected"
    ) {
      setError("Failed to load dashboard data. Retry in a few seconds.");
    }

    setLoading(false);
  }, [
    loadCasefileSummaryCached,
    selectedDrugId,
    setActiveSignals,
    setBeliefs,
    setEpisodes,
    setFdaActions,
    setIngestStatus,
    setProfile,
    setScorecard,
    setTimelinePoints,
  ]);

  useEffect(() => {
    void fetchGlobal();
  }, [fetchGlobal]);

  useEffect(() => {
    void fetchDrugScoped();
  }, [fetchDrugScoped]);

  useEffect(() => {
    if (loadedQuarters.length === 0) {
      setViewedQuarter(null);
      setIsPlaying(false);
      setDemoStage("baseline");
      setFastDemoReady(false);
      return;
    }
    setViewedQuarter((current) => {
      if (current && loadedQuarters.includes(current)) {
        return current;
      }
      return loadedQuarters[loadedQuarters.length - 1];
    });
  }, [loadedQuarters]);

  useEffect(() => {
    clearAutoEvidenceCaches();
    clearTimeTravelCaches();
    setEvidenceReportCache({});
  }, [clearAutoEvidenceCaches, clearTimeTravelCaches, selectedDrugId]);

  useEffect(() => {
    setDemoPresentationActive(false);
    setCasefileSummary(null);
  }, [selectedDrugId]);

  useEffect(() => {
    const persistedJobId = readPersistedRebuildJobId(selectedDrugId);
    setRebuildJob(null);
    setActiveRebuildJobId(persistedJobId);
    setRebuildJobError(null);
    setRebuildJobLoading(false);
    setCreatingRebuildJob(false);
    rebuildPollingInFlightRef.current = false;
    rebuildReadyHandledRef.current = null;
  }, [selectedDrugId]);

  useEffect(() => {
    if (!selectedDrugId) {
      return;
    }
    const persistedRebuildJobId = readPersistedRebuildJobId(selectedDrugId);
    if (!persistedRebuildJobId) {
      setRebuildJob(null);
      setActiveRebuildJobId(null);
      return;
    }

    const controller = new AbortController();

    void (async () => {
      try {
        const payload = await getActiveDrugFullHistoryRebuildJob(
          selectedDrugId,
          controller.signal,
        );
        setRebuildJob(payload);
        setActiveRebuildJobId(payload.id);
        persistRebuildJobId(selectedDrugId, payload.id);
        setRebuildJobError(null);
        setCreatingRebuildJob(false);
      } catch (nextError) {
        if (nextError instanceof Error && nextError.name === "AbortError") {
          return;
        }
        if (nextError instanceof ApiError && nextError.statusCode === 404) {
          return;
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [activeRebuildJobId, selectedDrugId]);

  useEffect(() => {
    if (!loadedQuarterSignatureRef.current) {
      loadedQuarterSignatureRef.current = loadedQuarterSignature;
      return;
    }
    if (loadedQuarterSignatureRef.current !== loadedQuarterSignature) {
      clearAutoEvidenceCaches();
      clearTimeTravelCaches();
    }
    loadedQuarterSignatureRef.current = loadedQuarterSignature;
  }, [clearAutoEvidenceCaches, clearTimeTravelCaches, loadedQuarterSignature]);

  useEffect(() => {
    return () => {
      autoEvidenceAbortRef.current?.abort();
      demoAbortRef.current?.abort();
      clearThoughtTimers();
    };
  }, [clearThoughtTimers]);

  useEffect(() => {
    if (!activeRebuildJobId) {
      setRebuildJobLoading(false);
      setCreatingRebuildJob(false);
      rebuildPollingInFlightRef.current = false;
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    const loadJob = async () => {
      if (rebuildPollingInFlightRef.current) {
        return;
      }
      rebuildPollingInFlightRef.current = true;
      try {
        setRebuildJobLoading(true);
        const payload = await getTrackingJob(
          activeRebuildJobId,
          controller.signal,
        );
        if (!cancelled) {
          setRebuildJob(payload);
          setRebuildJobError(null);
          setCreatingRebuildJob(false);
        }
      } catch (nextError) {
        if (
          !cancelled &&
          !(nextError instanceof Error && nextError.name === "AbortError")
        ) {
          const mappedError = getRebuildPollError(nextError);
          if (mappedError.clearPersistedJob) {
            clearPersistedRebuildJobId(selectedDrugId);
            setActiveRebuildJobId(null);
            setRebuildJob(null);
          }
          setRebuildJobError(mappedError.message);
          setCreatingRebuildJob(false);
        }
      } finally {
        if (!cancelled) {
          setRebuildJobLoading(false);
        }
        rebuildPollingInFlightRef.current = false;
      }
    };

    void loadJob();
    const poll = window.setInterval(() => {
      if (rebuildJob?.status === "ready" || rebuildJob?.status === "failed") {
        return;
      }
      void loadJob();
    }, 1000);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(poll);
    };
  }, [activeRebuildJobId, rebuildJob?.status, selectedDrugId]);

  useEffect(() => {
    if (!rebuildJob || rebuildJob.status !== "ready") {
      return;
    }
    if (rebuildReadyHandledRef.current === rebuildJob.id) {
      return;
    }
    rebuildReadyHandledRef.current = rebuildJob.id;

    let cancelled = false;
    void (async () => {
      resetCasefileRunState();
      await fetchGlobal();
      if (cancelled) {
        return;
      }
      await fetchDrugScoped();
    })().catch((nextError) => {
      if (!cancelled) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Full-history rebuild failed",
        );
      }
    });

    return () => {
      cancelled = true;
    };
  }, [fetchDrugScoped, fetchGlobal, rebuildJob, resetCasefileRunState]);

  useEffect(() => {
    autoEvidenceAbortRef.current?.abort();
    autoEvidenceAbortRef.current = null;
    const requestSeq = autoEvidenceRequestSeqRef.current + 1;
    autoEvidenceRequestSeqRef.current = requestSeq;

    // During active ingest runs, skip auto evidence fan-out requests.
    // This avoids request storms (diff + query + evidence fetches) while
    // quarters are still being ingested and state is not yet final.
    if (ingestAllProgress?.active || ingestThoughtStreaming) {
      setAutoEvidenceLoading(false);
      return;
    }

    if (!activeQuarter) {
      setAutoEvidenceResponse(null);
      setAutoEvidenceLoading(false);
      setAutoEvidenceError(null);
      setAutoFocusEvent(null);
      setAutoReinterpretedReportIds([]);
      return;
    }

    const currentQuarterPoints = timelinePoints.filter(
      (point) => point.quarter === activeQuarter,
    );
    const currentQuarterIndex = loadedQuarters.indexOf(activeQuarter);
    const previousQuarter =
      currentQuarterIndex > 0 ? loadedQuarters[currentQuarterIndex - 1] : null;
    const previousQuarterPoints = previousQuarter
      ? timelinePoints.filter((point) => point.quarter === previousQuarter)
      : [];

    const focusEvent = resolveSpotlightSignal({
      currentQuarterPoints,
      previousQuarterPoints,
    });
    setAutoFocusEvent(focusEvent);

    const cacheKey = `${selectedDrugId}|${activeQuarter}|${focusEvent ?? "none"}`;
    const cached = autoEvidenceCacheRef.current.get(cacheKey);
    if (cached) {
      cacheEvidenceReports(cached.response.evidence);
      setAutoEvidenceResponse(cached.response);
      setAutoReinterpretedReportIds(cached.reinterpretedReportIds);
      setAutoEvidenceLoading(false);
      setAutoEvidenceError(
        cached.response.evidence.length === 0
          ? "No report-level evidence found for this quarter yet."
          : null,
      );
      return;
    }

    setAutoEvidenceResponse(null);
    setAutoReinterpretedReportIds([]);
    setAutoEvidenceLoading(true);
    setAutoEvidenceError(null);

    const timer = window.setTimeout(() => {
      const controller = new AbortController();
      autoEvidenceAbortRef.current = controller;
      const reinterpretKey = `${selectedDrugId}|${activeQuarter}`;

      const reinterpretPromise = (async (): Promise<string[]> => {
        const cachedReinterpreted =
          autoReinterpretCacheRef.current.get(reinterpretKey);
        if (cachedReinterpreted) {
          return cachedReinterpreted;
        }
        const pair = pickBeliefPairForQuarterDiff({
          beliefs,
          activeQuarter,
          loadedQuarters,
        });
        if (!pair) {
          autoReinterpretCacheRef.current.set(reinterpretKey, []);
          return [];
        }
        try {
          const diff = await loadBeliefDiffCached(pair.beforeId, pair.afterId);
          const reinterpreted = diff.reinterpreted_report_ids ?? [];
          autoReinterpretCacheRef.current.set(reinterpretKey, reinterpreted);
          return reinterpreted;
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") {
            throw err;
          }
          return [];
        }
      })();

      void reinterpretPromise
        .then(async (reinterpretedReportIds) => {
          if (requestSeq !== autoEvidenceRequestSeqRef.current) {
            return;
          }
          // Priority 1: reinterpretation evidence for the quarter.
          if (reinterpretedReportIds.length > 0) {
            const settled = await Promise.allSettled(
              reinterpretedReportIds
                .slice(0, 12)
                .map((reportId) => getEvidence(reportId, controller.signal)),
            );
            const reinterpretEvidence = settled
              .filter(
                (item): item is PromiseFulfilledResult<FAERSReport> =>
                  item.status === "fulfilled",
              )
              .map((item) => item.value);

            if (requestSeq !== autoEvidenceRequestSeqRef.current) {
              return;
            }
            if (reinterpretEvidence.length > 0) {
              cacheEvidenceReports(reinterpretEvidence);
              const response: QueryResponse = {
                answer_text:
                  "Auto-selected reinterpretation evidence for this quarter.",
                confidence: 100,
                signal_summary: currentQuarterPoints,
                evidence: reinterpretEvidence,
                episodic_context: [],
                belief_id: "auto:reinterpretation",
                foresight_memory_ids: [],
              };
              setAutoEvidenceResponse(response);
              setAutoReinterpretedReportIds(reinterpretedReportIds);
              setAutoEvidenceLoading(false);
              setAutoEvidenceError(null);
              autoEvidenceCacheRef.current.set(cacheKey, {
                response,
                reinterpretedReportIds,
              });
              return;
            }
          }

          if (!focusEvent) {
            setAutoEvidenceLoading(false);
            setAutoEvidenceResponse(null);
            setAutoReinterpretedReportIds(reinterpretedReportIds);
            setAutoEvidenceError(
              "No report-level evidence found for this quarter yet.",
            );
            return;
          }

          const questionText = buildAutoEvidenceQuestion({
            drugId: selectedDrugId,
            event: focusEvent,
          });
          const response = await postQuery(
            selectedDrugId,
            questionText,
            activeQuarter,
            controller.signal,
          );
          if (requestSeq !== autoEvidenceRequestSeqRef.current) {
            return;
          }

          appendQueryThoughts({
            quarter: activeQuarter,
            question: questionText,
            response,
            source: "auto",
          });
          cacheEvidenceReports(response.evidence);
          setAutoEvidenceResponse(response);
          setAutoReinterpretedReportIds(reinterpretedReportIds);
          setAutoEvidenceLoading(false);
          setAutoEvidenceError(
            response.evidence.length === 0
              ? "No report-level evidence found for this quarter yet."
              : null,
          );
          autoEvidenceCacheRef.current.set(cacheKey, {
            response,
            reinterpretedReportIds,
          });
        })
        .catch((err: unknown) => {
          if (requestSeq !== autoEvidenceRequestSeqRef.current) {
            return;
          }
          if (err instanceof DOMException && err.name === "AbortError") {
            return;
          }
          setAutoEvidenceLoading(false);
          setAutoEvidenceResponse(null);
          setAutoReinterpretedReportIds([]);
          setAutoEvidenceError(
            "No report-level evidence found for this quarter yet.",
          );
        });
    }, 220);

    return () => {
      window.clearTimeout(timer);
    };
  }, [
    activeQuarter,
    appendQueryThoughts,
    cacheEvidenceReports,
    beliefs,
    ingestAllProgress?.active,
    ingestThoughtStreaming,
    loadBeliefDiffCached,
    loadedQuarters,
    selectedDrugId,
    timelinePoints,
  ]);

  useEffect(() => {
    if (!ingestProgress) {
      return;
    }

    if (ingestProgress.phase === "starting") {
      setAgentRunState("running");
      if (thoughtQuarterRef.current !== ingestProgress.quarter) {
        clearThoughtTimers();
        seenThoughtIdsRef.current.clear();
        setAgentLog([]);
        thoughtQuarterRef.current = ingestProgress.quarter;
      }
    } else if (
      ingestProgress.phase === "loading_reports" ||
      ingestProgress.phase === "computing_signals" ||
      ingestProgress.phase === "posting_evermemos" ||
      ingestProgress.phase === "generating_beliefs"
    ) {
      setAgentRunState("running");
    } else if (ingestProgress.phase === "done") {
      setAgentRunState("complete");
    } else if (ingestProgress.phase === "error") {
      setAgentRunState("error");
    }

    const thoughts = ingestProgress.thoughts ?? [];
    if (thoughts.length === 0) {
      return;
    }

    let queuedNewThought = false;
    thoughts.forEach((thought, index) => {
      const thoughtId = [
        ingestProgress.quarter,
        ingestProgress.phase,
        thought.timestamp,
        thought.type,
        String(index),
        thought.content,
      ].join("|");
      if (
        seenThoughtIdsRef.current.has(thoughtId) ||
        queuedThoughtIdsRef.current.has(thoughtId)
      ) {
        return;
      }
      queuedThoughtIdsRef.current.add(thoughtId);
      thoughtQueueRef.current.push({
        id: thoughtId,
        type: thought.type,
        content: thought.content,
        timestamp: thought.timestamp,
        origin: "server",
        memoryRefs: thought.memory_refs ?? undefined,
        metadata:
          (thought.metadata as Record<string, unknown> | null | undefined) ??
          undefined,
      });
      queuedNewThought = true;
    });
    if (queuedNewThought) {
      pumpThoughtQueue();
    }
  }, [clearThoughtTimers, ingestProgress, pumpThoughtQueue]);

  useEffect(() => {
    if (ingestProgress?.phase !== "done") {
      return;
    }
    const completedQuarter = ingestProgress.quarter;
    if (!claimQuarterOnce(lastSyntheticSummaryQuarterRef, completedQuarter)) {
      return;
    }

    appendSyntheticThought({
      id: syntheticThoughtId("summary", selectedDrugId, completedQuarter),
      type: "reasoning",
      content: buildQuarterSummaryThought(
        completedQuarter,
        signalSnapshotForQuarter(timelinePoints, completedQuarter),
      ),
      quarter: completedQuarter,
      source: "quarter_summary",
    });
  }, [
    appendSyntheticThought,
    ingestProgress?.phase,
    ingestProgress?.quarter,
    selectedDrugId,
    timelinePoints,
  ]);

  useEffect(() => {
    if (!viewedQuarter) {
      return;
    }
    if (loading && signalSnapshot.length === 0) {
      // Avoid locking in an empty-state observation before timeline data arrives.
      return;
    }
    if (ingestThoughtStreaming || ingestAllProgress?.active) {
      return;
    }
    if (!claimQuarterOnce(lastSyntheticObservationQuarterRef, viewedQuarter)) {
      return;
    }

    appendSyntheticThought({
      id: syntheticThoughtId("observation", selectedDrugId, viewedQuarter),
      type: "perceive",
      content: buildTimeTravelObservationThought(
        viewedQuarter,
        signalSnapshot,
        scorecardAsOfViewed,
      ),
      quarter: viewedQuarter,
      source: "time_travel",
    });
  }, [
    appendSyntheticThought,
    ingestAllProgress?.active,
    ingestThoughtStreaming,
    loading,
    scorecardAsOfViewed,
    selectedDrugId,
    signalSnapshot,
    viewedQuarter,
  ]);

  useEffect(() => {
    const latest = agentLog.at(-1);
    if (!latest || latest.type !== "reinterpretation") {
      return;
    }
    if (lastReinterpretToastRef.current === latest.id) {
      return;
    }
    lastReinterpretToastRef.current = latest.id;
    const reason =
      typeof latest.metadata?.reason === "string" ? latest.metadata.reason : "";
    const signalMatch = /Signal '([^']+)'/.exec(reason);
    const adverseEvent = signalMatch?.[1] ?? "GI safety pattern";
    const countValue =
      typeof latest.metadata?.reinterpreted_count === "number"
        ? latest.metadata.reinterpreted_count
        : 0;

    const toastId = `reinterpret:${latest.id}`;
    setSignalToasts((current) =>
      [
        ...current,
        {
          id: toastId,
          kind: "reinterpretation" as const,
          adverseEvent,
          quarter: activeQuarter ?? latest.timestamp.slice(0, 10),
          ror: null,
          ciLower: null,
          ciUpper: null,
          cumulativeCount: countValue,
        },
      ].slice(-5),
    );
    window.setTimeout(() => {
      setSignalToasts((current) => current.filter((row) => row.id !== toastId));
    }, 4200);
  }, [activeQuarter, agentLog]);

  useEffect(() => {
    if (ingestProgress?.phase !== "done") {
      return;
    }
    // During full simulation, defer refreshes until the run completes to avoid
    // out-of-order quarter snapshots racing and overwriting final state.
    if (ingestAllProgress?.active) {
      return;
    }
    void fetchDrugScoped();
  }, [fetchDrugScoped, ingestAllProgress?.active, ingestProgress]);

  useEffect(() => {
    if (!isPlaying || loadedQuarters.length <= 1 || !viewedQuarter) {
      return;
    }

    const timer = window.setInterval(() => {
      setViewedQuarter((current) => {
        if (!current) {
          return loadedQuarters[0] ?? null;
        }
        const currentIndex = loadedQuarters.indexOf(current);
        if (currentIndex < 0 || currentIndex >= loadedQuarters.length - 1) {
          setIsPlaying(false);
          return current;
        }
        playbackAdvanceRef.current = true;
        return loadedQuarters[currentIndex + 1];
      });
    }, playSpeedMs);

    return () => {
      window.clearInterval(timer);
    };
  }, [isPlaying, loadedQuarters, playSpeedMs, viewedQuarter]);

  useEffect(() => {
    if (!viewedQuarter) {
      return;
    }

    const previousQuarter = previousViewedQuarterRef.current;
    if (
      playbackAdvanceRef.current &&
      previousQuarter &&
      previousQuarter !== viewedQuarter
    ) {
      const previousPoints = timelinePoints.filter(
        (point) => point.quarter === previousQuarter,
      );
      const currentPoints = timelinePoints.filter(
        (point) => point.quarter === viewedQuarter,
      );
      const discovered = detectNewSignals(previousPoints, currentPoints).map(
        (toast, idx) => ({
          ...toast,
          id: `${toast.id}:${Date.now()}:${idx}`,
        }),
      );
      if (discovered.length > 0) {
        setSignalToasts((current) => [...current, ...discovered].slice(-5));
        for (const toast of discovered) {
          const toastId = toast.id;
          window.setTimeout(() => {
            setSignalToasts((current) =>
              current.filter((row) => row.id !== toastId),
            );
          }, 3000);
        }
      }
    }

    previousViewedQuarterRef.current = viewedQuarter;
    playbackAdvanceRef.current = false;
  }, [timelinePoints, viewedQuarter]);

  async function handleIngest(): Promise<void> {
    cancelDemoRun();
    setError(null);
    setIsPlaying(false);
    setIngestAllProgress(null);
    setForcedBeliefTab(null);
    setFastDemoReady(false);
    setAgentRunState("running");
    try {
      const updatedStatus = await postIngestNextQuarter(selectedDrugId);
      setIngestStatus(updatedStatus);
      const latestQuarter = updatedStatus.quarters_loaded.at(-1) ?? null;
      if (latestQuarter) {
        setViewedQuarter(latestQuarter);
      }
      void fetchDrugScoped();
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setAgentRunState("error");
      }
      setError(err instanceof Error ? err.message : "Ingestion failed");
    }
  }

  async function handleIngestAll(): Promise<void> {
    setError(null);
    setIsPlaying(false);
    setForcedBeliefTab(null);
    setDemoRunning(false);
    setFastDemoReady(false);
    const runToken = demoRunTokenRef.current + 1;
    demoRunTokenRef.current = runToken;
    const isActive = () => demoRunTokenRef.current === runToken;

    try {
      let loopGuard = 0;
      let statusSnapshot = ingestStatus;
      const startingLoaded = ingestStatus?.quarters_loaded.length ?? 0;
      const startingTotalAvailable = ingestStatus?.total_quarters_available;
      setIngestAllProgress({
        active: true,
        completedQuarters: 0,
        totalQuarters:
          typeof startingTotalAvailable === "number"
            ? Math.max(0, startingTotalAvailable - startingLoaded)
            : null,
      });
      setAgentRunState("running");

      while (statusSnapshot?.next_quarter && loopGuard < 64) {
        if (!isActive()) {
          break;
        }
        const controller = new AbortController();
        demoAbortRef.current = controller;
        const updatedStatus = await postIngestNextQuarter(
          selectedDrugId,
          controller.signal,
        ).finally(() => {
          if (demoAbortRef.current === controller) {
            demoAbortRef.current = null;
          }
        });
        setIngestStatus(updatedStatus);
        const latestQuarter = updatedStatus.quarters_loaded.at(-1) ?? null;
        if (latestQuarter) {
          setViewedQuarter(latestQuarter);
        }
        const completed = Math.max(
          0,
          updatedStatus.quarters_loaded.length - startingLoaded,
        );
        const total =
          typeof updatedStatus.total_quarters_available === "number"
            ? Math.max(
                0,
                updatedStatus.total_quarters_available - startingLoaded,
              )
            : typeof startingTotalAvailable === "number"
              ? Math.max(0, startingTotalAvailable - startingLoaded)
              : null;
        setIngestAllProgress({
          active: true,
          completedQuarters: completed,
          totalQuarters: total,
        });
        statusSnapshot = updatedStatus;
        loopGuard += 1;
        if (!isActive()) {
          break;
        }
      }
      if (!isActive()) {
        setIngestAllProgress((current) =>
          current ? { ...current, active: false } : null,
        );
        return;
      }
      await fetchDrugScoped();
      if (!isActive()) {
        setIngestAllProgress((current) =>
          current ? { ...current, active: false } : null,
        );
        return;
      }
      setIngestAllProgress((current) =>
        current ? { ...current, active: false } : null,
      );
      setAgentRunState("complete");
      if (
        !analystWorkspaceOpen &&
        statusSnapshot?.quarters_loaded.includes(VALIDATION_QUARTER)
      ) {
        setDemoStage("validation");
      }
      setFastDemoReady(false);
    } catch (err) {
      setIngestAllProgress((current) =>
        current ? { ...current, active: false } : null,
      );
      if (err instanceof DOMException && err.name === "AbortError") {
        setAgentRunState("cancelled");
        return;
      }
      setError(err instanceof Error ? err.message : "Full simulation failed");
    }
  }

  function handleCancelIngestAll(): void {
    cancelDemoRun();
    setIngestAllProgress((current) =>
      current ? { ...current, active: false } : null,
    );
    setFastDemoReady(false);
  }

  async function bootstrapCompetitionDemo(): Promise<void> {
    await postSeedDemo({
      drugIds: ["semaglutide"],
      preloadQuarters: SEMAGLUTIDE_DEMO_BASELINE_QUARTERS,
    });
    await postSeedDemo({
      drugIds: ["minoxidil"],
      preloadQuarters: FULL_DEMO_HISTORY_QUARTERS,
    });
  }

  async function handleStartFromEntrypoint(): Promise<void> {
    if (startDemoLoading) {
      return;
    }
    setStartDemoLoading(true);
    setError(null);
    setDrawerOpen(false);
    setDrawerTab("query");
    try {
      await bootstrapCompetitionDemo();
      setDemoPresentationActive(selectedDrugId === "semaglutide");
      await fetchGlobal();
      await fetchDrugScoped();
    } finally {
      setStartDemoLoading(false);
    }
  }

  async function handleReset(): Promise<void> {
    cancelDemoRun();
    setError(null);
    setIsPlaying(false);
    setIngestAllProgress(null);
    const confirmed = window.confirm(
      "Reset agent memory and clear loaded data, generated beliefs, and predictions?",
    );
    if (!confirmed) {
      return;
    }
    try {
      await postIngestReset(selectedDrugId, false);
      resetCasefileRunState();
      await fetchGlobal();
      await fetchDrugScoped();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  async function handleRebuildFullHistory(): Promise<void> {
    cancelDemoRun();
    setError(null);
    setIsPlaying(false);
    setIngestAllProgress(null);
    const confirmed = window.confirm(
      "Download the full matched FAERS history for this drug, clear the current casefile analysis, and rebuild from baseline?",
    );
    if (!confirmed) {
      return;
    }

    setCreatingRebuildJob(true);
    setRebuildJobError(null);
    setRebuildJob(null);
    setActiveRebuildJobId(null);
    rebuildReadyHandledRef.current = null;

    try {
      const job = await postDrugFullHistoryRebuildJob(selectedDrugId, {
        baselineQuarters: 4,
        preferCached: false,
      });
      persistRebuildJobId(selectedDrugId, job.id);
      setActiveRebuildJobId(job.id);
      setRebuildJob(job);
    } catch (err) {
      setCreatingRebuildJob(false);
      setRebuildJobError(getRebuildStartErrorMessage(err));
    }
  }

  function handleDismissRebuildStatus(): void {
    clearPersistedRebuildJobId(selectedDrugId);
    setActiveRebuildJobId(null);
    setRebuildJob(null);
    setRebuildJobError(null);
    setRebuildJobLoading(false);
    setCreatingRebuildJob(false);
    rebuildPollingInFlightRef.current = false;
    rebuildReadyHandledRef.current = null;
  }

  async function handleQuery(question: string): Promise<void> {
    cancelDemoRun();
    setFastDemoReady(false);
    if (!activeQuarter) {
      setError("Load at least one quarter before running a query.");
      return;
    }
    setQueryLoading(true);
    try {
      const response = await postQuery(selectedDrugId, question, activeQuarter);
      appendQueryThoughts({
        quarter: activeQuarter,
        question,
        response,
        source: "manual",
      });
      cacheEvidenceReports(response.evidence);
      setQueryResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setQueryLoading(false);
    }
  }

  async function handleRequestDiff(
    beforeId: string,
    afterId: string,
  ): Promise<void> {
    if (!beforeId || !afterId) {
      return;
    }
    setDiffLoading(true);
    try {
      const diff = await loadBeliefDiffCached(beforeId, afterId);
      setBeliefDiff(diff);
      beliefDiffCacheRef.current.set(
        buildBeliefDiffCacheKey(beforeId, afterId),
        diff,
      );

      const reinterpretationIds = diff.reinterpreted_report_ids.slice(0, 12);
      if (reinterpretationIds.length === 0) {
        setReinterpretationMarkers([]);
        return;
      }

      const settled = await Promise.allSettled(
        reinterpretationIds.map(async (reportId) => {
          const report = await getEvidence(reportId);
          return {
            report,
            quarter: isoDateToQuarter(report.receivedate),
          };
        }),
      );

      const reports = settled
        .filter(
          (
            item,
          ): item is PromiseFulfilledResult<{
            report: FAERSReport;
            quarter: string | null;
          }> => item.status === "fulfilled",
        )
        .map((item) => item.value.report);
      cacheEvidenceReports(reports);

      const markers = settled
        .filter(
          (
            item,
          ): item is PromiseFulfilledResult<{
            report: FAERSReport;
            quarter: string | null;
          }> => item.status === "fulfilled",
        )
        .map((item) => item.value)
        .filter((item) => item.quarter !== null)
        .map((item) => ({
          quarter: item.quarter as string,
          reportId: item.report.safetyreportid,
        }));
      setReinterpretationMarkers(markers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Diff failed");
    } finally {
      setDiffLoading(false);
    }
  }

  function toggleEvent(event: string): void {
    setSelectedEvents((current) => {
      if (current.includes(event)) {
        if (current.length === 1) {
          return current;
        }
        return current.filter((entry) => entry !== event);
      }
      return [...current, event].slice(-MAX_TRAJECTORY_EVENTS);
    });
  }

  function stepQuarter(delta: number): void {
    cancelDemoRun();
    setForcedBeliefTab(null);
    if (!viewedQuarter || loadedQuarters.length === 0) {
      return;
    }
    const currentIndex = loadedQuarters.indexOf(viewedQuarter);
    if (currentIndex < 0) {
      return;
    }
    const targetIndex = Math.min(
      loadedQuarters.length - 1,
      Math.max(0, currentIndex + delta),
    );
    setViewedQuarter(loadedQuarters[targetIndex]);
  }

  const pushSignalToasts = useCallback(
    (previousQuarter: string, nextQuarter: string) => {
      const previousPoints = timelinePoints.filter(
        (point) => point.quarter === previousQuarter,
      );
      const currentPoints = timelinePoints.filter(
        (point) => point.quarter === nextQuarter,
      );
      const discovered = detectNewSignals(previousPoints, currentPoints).map(
        (toast, idx) => ({
          ...toast,
          id: `${toast.id}:${Date.now()}:${idx}`,
        }),
      );
      if (discovered.length === 0) {
        return;
      }
      setSignalToasts((current) => [...current, ...discovered].slice(-5));
      for (const toast of discovered) {
        const toastId = toast.id;
        window.setTimeout(() => {
          setSignalToasts((current) =>
            current.filter((row) => row.id !== toastId),
          );
        }, 3000);
      }
    },
    [timelinePoints],
  );

  const pushTimedToast = useCallback(
    (toast: SignalAlert, durationMs = 3200) => {
      setSignalToasts((current) => [...current, toast].slice(-5));
      const toastId = toast.id;
      window.setTimeout(() => {
        setSignalToasts((current) =>
          current.filter((row) => row.id !== toastId),
        );
      }, durationMs);
    },
    [],
  );

  const pushCueToast = useCallback(
    (params: {
      quarter: string;
      adverseEvent: string;
      headline: string;
      durationMs?: number;
    }) => {
      const point = timelinePoints.find(
        (row) =>
          row.quarter === params.quarter &&
          row.adverse_event === params.adverseEvent,
      );
      pushTimedToast(
        {
          id: `cue:${params.headline}:${params.adverseEvent}:${params.quarter}:${Date.now()}`,
          headline: params.headline,
          adverseEvent: params.adverseEvent,
          quarter: params.quarter,
          ror: point?.ror ?? null,
          ciLower: point?.ror_ci_lower ?? null,
          ciUpper: point?.ror_ci_upper ?? null,
          cumulativeCount: point?.cumulative_count ?? 0,
        },
        params.durationMs ?? 3200,
      );
    },
    [pushTimedToast, timelinePoints],
  );

  function resetDemoViewport(): void {
    setIsPlaying(false);
    setSignalToasts([]);
    setBeliefDiff(null);
    setReinterpretationMarkers([]);
    setDrawerOpen(false);
    setDrawerTab("query");
    setForcedBeliefTab(null);
    setShowMemorySources(false);
  }

  async function runStoryDemoToQuarter(
    targetQuarter: string,
    options: {
      stageOnArrival: DemoStage;
      fastDemoReadyOnArrival?: boolean;
      animateLoadedTimeline?: boolean;
      cueHeadline?: string | null;
    },
  ): Promise<void> {
    if (demoRunning) {
      cancelDemoRun();
      return;
    }

    const runToken = demoRunTokenRef.current + 1;
    demoRunTokenRef.current = runToken;
    const isActive = () => demoRunTokenRef.current === runToken;
    const wait = (ms: number) =>
      new Promise<void>((resolve) => window.setTimeout(resolve, ms));
    const baselineQuarter = loadedQuarters.includes(BASELINE_QUARTER)
      ? BASELINE_QUARTER
      : (loadedQuarters[0] ?? null);

    setDemoRunning(true);
    setError(null);
    resetDemoViewport();

    const travelLoadedTimeline = async (
      fromQuarter: string,
      toQuarter: string,
      stepMs: number,
    ): Promise<string | null> => {
      if (
        !loadedQuarters.includes(fromQuarter) ||
        !loadedQuarters.includes(toQuarter)
      ) {
        return null;
      }
      let cursor = fromQuarter;
      while (
        loadedQuarters.indexOf(cursor) < loadedQuarters.indexOf(toQuarter)
      ) {
        const next = loadedQuarters[loadedQuarters.indexOf(cursor) + 1];
        if (!next) {
          break;
        }
        pushSignalToasts(cursor, next);
        cursor = next;
        setViewedQuarter(next);
        await wait(stepMs);
        if (!isActive()) {
          return null;
        }
      }
      return cursor;
    };

    try {
      if (baselineQuarter) {
        setViewedQuarter(baselineQuarter);
        await wait(220);
        if (!isActive()) {
          return;
        }
      }

      let cursor: string | null = baselineQuarter;
      let statusSnapshot = ingestStatus;
      const latestKnownQuarter = statusSnapshot?.quarters_loaded.at(-1) ?? null;

      if (
        typeof baselineQuarter === "string" &&
        latestKnownQuarter &&
        loadedQuarters.includes(targetQuarter)
      ) {
        cursor = await travelLoadedTimeline(
          baselineQuarter,
          targetQuarter,
          options.animateLoadedTimeline ? 170 : 40,
        );
        if (!isActive()) {
          return;
        }
      } else {
        if (
          typeof baselineQuarter === "string" &&
          latestKnownQuarter &&
          loadedQuarters.includes(latestKnownQuarter) &&
          loadedQuarters.indexOf(latestKnownQuarter) >
            loadedQuarters.indexOf(baselineQuarter)
        ) {
          cursor = await travelLoadedTimeline(
            baselineQuarter,
            latestKnownQuarter,
            80,
          );
          if (!isActive()) {
            return;
          }
        }

        let loopGuard = 0;
        while (statusSnapshot?.next_quarter && loopGuard < 64) {
          const controller = new AbortController();
          demoAbortRef.current = controller;
          const updatedStatus = await postIngestNextQuarter(
            selectedDrugId,
            controller.signal,
          ).finally(() => {
            if (demoAbortRef.current === controller) {
              demoAbortRef.current = null;
            }
          });
          statusSnapshot = updatedStatus;
          setIngestStatus(updatedStatus);
          const latestQuarter = updatedStatus.quarters_loaded.at(-1) ?? null;
          if (latestQuarter) {
            if (cursor) {
              pushSignalToasts(cursor, latestQuarter);
            }
            cursor = latestQuarter;
            setViewedQuarter(latestQuarter);
          }
          loopGuard += 1;
          if (!isActive()) {
            return;
          }
          if (latestQuarter === targetQuarter) {
            break;
          }
        }
      }

      await fetchDrugScoped();
      if (!isActive()) {
        return;
      }

      const arrivalQuarter =
        targetQuarter === VALIDATION_QUARTER &&
        statusSnapshot?.quarters_loaded.includes(VALIDATION_QUARTER)
          ? VALIDATION_QUARTER
          : targetQuarter === REVEAL_QUARTER &&
              statusSnapshot?.quarters_loaded.includes(REVEAL_QUARTER)
            ? REVEAL_QUARTER
            : targetQuarter === FAST_DEMO_QUARTER &&
                statusSnapshot?.quarters_loaded.includes(FAST_DEMO_QUARTER)
              ? FAST_DEMO_QUARTER
              : (cursor ?? baselineQuarter ?? targetQuarter);

      setViewedQuarter(arrivalQuarter);
      setForcedBeliefTab(options.stageOnArrival === "baseline" ? null : "gi");
      setDemoStage(options.stageOnArrival);
      setFastDemoReady(Boolean(options.fastDemoReadyOnArrival));

      if (options.cueHeadline && options.stageOnArrival !== "baseline") {
        pushCueToast({
          quarter: arrivalQuarter,
          adverseEvent: "Ileus",
          headline: options.cueHeadline,
          durationMs: 3600,
        });
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setAgentRunState("cancelled");
        return;
      }
      setError(err instanceof Error ? err.message : "Demo run failed");
    } finally {
      if (isActive()) {
        setDemoRunning(false);
      }
    }
  }

  async function handleShowFdaReceipt(): Promise<void> {
    setDemoPresentationActive(true);
    await runStoryDemoToQuarter(VALIDATION_QUARTER, {
      stageOnArrival: "validation",
      cueHeadline: "FDA Receipt",
    });
  }

  async function handleFastDemo(): Promise<void> {
    setDemoPresentationActive(true);
    await runStoryDemoToQuarter(FAST_DEMO_QUARTER, {
      stageOnArrival: "baseline",
      fastDemoReadyOnArrival: true,
      animateLoadedTimeline: false,
      cueHeadline: null,
    });
  }

  async function handleRunDemo(): Promise<void> {
    if (demoRunning) {
      cancelDemoRun();
      return;
    }
    setDemoPresentationActive(true);
    if (demoStage === "reveal") {
      await handleShowFdaReceipt();
      return;
    }
    await runStoryDemoToQuarter(REVEAL_QUARTER, {
      stageOnArrival: "reveal",
      animateLoadedTimeline: true,
      cueHeadline: "Meaning Changed",
    });
  }

  function handleOpenAnalystWorkspace(): void {
    cancelDemoRun();
    analystWorkspaceScrollRequestedRef.current = true;
    setDemoStage("analyst");
    setFastDemoReady(false);
  }

  function handleCloseAnalystWorkspace(): void {
    analystWorkspaceScrollRequestedRef.current = false;
    setDemoStage(
      activeQuarter === VALIDATION_QUARTER
        ? "validation"
        : activeQuarter === REVEAL_QUARTER
          ? "reveal"
          : "baseline",
    );
  }

  const suggestedEvents =
    selectedEvents.length > 0
      ? selectedEvents
      : activeSignals
          .slice(0, MAX_TRAJECTORY_EVENTS)
          .map((item) => item.adverse_event);

  const drawerTabs = [
    { key: "belief", label: "Belief Diff" },
    { key: "episodic", label: "Episodes" },
    { key: "query", label: "Query" },
    { key: "all", label: "All" },
  ] as const;
  const showAnalystWorkspaceToggle = !showFirstLoadEntrypoint;
  const proofChain = (
    <MemoryNecessityProof
      activeQuarter={activeQuarter}
      drugId={selectedDrugId}
      evidenceReport={(autoEvidenceResponse?.evidence ?? [])[0] ?? null}
      episodicMemoryId={currentEpisode?.memory_id ?? null}
      episodicSummary={currentEpisode?.narrative ?? null}
      profileMemoryId={profileMemoryId}
      profileSummary={profile?.current_assessment ?? null}
      foresightEntry={keyReceipt}
      showMemorySources={showMemorySources}
      onOpenEvidence={openEvidenceDrawer}
      onOpenEventLogMemory={openEventLogMemory}
      onOpenMemory={(memoryId) => {
        const episode = episodicMemoryById.get(memoryId);
        if (episode) {
          openEpisodicTimelineMemory(episode);
          return;
        }
        if (memoryId === profileMemoryId) {
          openProfileMemory();
        }
      }}
      onOpenForesightMemory={openForesightMemory}
    />
  );

  const timeTravelExplorer = (
    <KnowledgeTimeExplorer
      quarters={loadedQuarters}
      selectedQuarter={viewedQuarter}
      onChangeQuarter={(quarter) => {
        cancelDemoRun();
        setForcedBeliefTab(null);
        setFastDemoReady(false);
        setViewedQuarter(quarter);
      }}
      onTogglePlay={() => {
        cancelDemoRun();
        setForcedBeliefTab(null);
        setFastDemoReady(false);
        setIsPlaying((current) => !current);
      }}
      onStep={stepQuarter}
      onJumpStart={() => {
        cancelDemoRun();
        setIsPlaying(false);
        setForcedBeliefTab(null);
        setFastDemoReady(false);
        setViewedQuarter(loadedQuarters[0] ?? null);
      }}
      onJumpEnd={() => {
        cancelDemoRun();
        setIsPlaying(false);
        setForcedBeliefTab(null);
        setFastDemoReady(false);
        setViewedQuarter(loadedQuarters[loadedQuarters.length - 1] ?? null);
      }}
      isPlaying={isPlaying}
      speedMs={playSpeedMs}
      onSpeedMsChange={setPlaySpeedMs}
      signalSnapshot={signalSnapshot}
      beliefsCurrentQuarter={beliefsCurrentQuarter}
      beliefsPreviousQuarter={beliefsPreviousQuarter}
      reinterpretationCount={beliefDiff?.reinterpreted_report_ids.length ?? 0}
      showMemorySources={showMemorySources}
      forcedBeliefTab={forcedBeliefTab}
      onOpenEpisodicMemory={openEpisodicMemoryFromBelief}
    />
  );

  return (
    <div className="min-h-screen bg-[var(--bg-root)] text-[var(--text-primary)]">
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(212,149,106,0.06),transparent)]" />
      </div>

      <main className="mx-auto max-w-[1440px] px-5 pb-12 pt-6 lg:px-8">
        <header className="mb-8 animate-fade-up">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <Link to="/discover" className="block">
                <h1 className="font-display text-3xl font-semibold tracking-tight text-[var(--text-primary)] lg:text-[2.5rem]">
                  VigiLens
                </h1>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Memory-native pharmacovigilance case system
                </p>
              </Link>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {!showFirstLoadEntrypoint ? (
                <DemoModeButton
                  stage={demoStage}
                  running={demoRunning}
                  fastDemoReady={fastDemoReady}
                  onRun={handleRunDemo}
                  onFastDemo={handleFastDemo}
                />
              ) : null}
              {showAnalystWorkspaceToggle ? (
                <button
                  type="button"
                  onClick={
                    analystWorkspaceOpen
                      ? handleCloseAnalystWorkspace
                      : handleOpenAnalystWorkspace
                  }
                  className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                >
                  {analystWorkspaceOpen
                    ? "Close analyst workspace"
                    : "Open analyst workspace"}
                </button>
              ) : null}
              <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-panel)] px-3 py-1.5 text-xs text-[var(--text-secondary)]">
                <span
                  className={`h-2 w-2 rounded-full ${
                    healthOk === false
                      ? "bg-red-400 shadow-[0_0_6px_rgba(239,68,68,0.4)]"
                      : healthOk
                        ? "bg-emerald-400 shadow-[0_0_6px_rgba(74,222,128,0.4)]"
                        : "bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.35)]"
                  }`}
                />
                <span>
                  {healthOk === false
                    ? "Offline"
                    : healthOk
                      ? "Connected"
                      : "Checking"}
                </span>
              </div>
            </div>
          </div>
        </header>

        {error ? (
          <div className="mb-5 flex items-start gap-3 rounded-lg border border-red-500/20 bg-[var(--danger-dim)] px-4 py-3 text-sm text-red-200">
            <span className="mt-0.5 shrink-0 text-red-400">!</span>
            <span>{error}</span>
          </div>
        ) : null}

        {showFirstLoadEntrypoint ? (
          <div id="section-overview">
            <FirstLoadDemoEntrypoint
              drugLabel={selectedDrug?.generic_name ?? selectedDrugId}
              loading={loading}
              starting={startDemoLoading || Boolean(ingestAllProgress?.active)}
              canStart={canStartFromEntrypoint}
              nextQuarter={ingestStatus?.next_quarter ?? null}
              onStart={handleStartFromEntrypoint}
            />
          </div>
        ) : (
          <>
            <div id="section-overview">
              {isPrimaryDemoDrug ? (
                <StoryHeader
                  viewingQuarter={activeQuarter}
                  totalReportsLoaded={totalReportsLoadedDisplay}
                  demoStage={demoStage}
                  memoryStatusLabel={memoryStatus.label}
                  memoryStatusTone={memoryStatus.tone}
                  beliefDiff={beliefDiff}
                  primaryReceipt={keyReceipt}
                  secondaryReceiptCount={secondaryReceiptCount}
                />
              ) : (
                <CasefileIntro
                  drugLabel={selectedDrug?.generic_name ?? selectedDrugId}
                  brandNames={selectedDrug?.brand_names ?? []}
                  totalReports={totalReportsLoadedDisplay}
                  activeQuarter={activeQuarter}
                  casefileSummary={casefileSummary}
                  onRebuildFullHistory={handleRebuildFullHistory}
                  fullHistoryJob={rebuildJob}
                  fullHistoryLoading={rebuildJobLoading || creatingRebuildJob}
                  fullHistoryError={rebuildJobError}
                />
              )}
            </div>
            <MetricsBar
              totalReports={metricsAsOf.totalReports}
              activeSignals={metricsAsOf.activeSignals}
              beliefsTracked={metricsAsOf.beliefsTracked}
              predictionsValidated={metricsAsOf.predictionsValidated}
              predictionsTotal={metricsAsOf.predictionsTotal}
              quartersLoaded={metricsAsOf.quartersLoaded}
              predictionLabel={predictionMetric.label}
              predictionValue={predictionMetric.value}
              predictionSuffix={predictionMetric.suffix}
            />
            <div className="mt-5">
              <SituationAnalysisCard
                drugId={selectedDrugId}
                quarter={activeQuarter}
              />
            </div>
            <section id="section-time-travel" className="mt-5">
              {timeTravelExplorer}
            </section>
            <div id="section-belief-revision">
              <BeliefRevisionHero
                activeQuarter={activeQuarter}
                diff={beliefDiff}
                drugLabel={selectedDrug?.generic_name ?? selectedDrugId}
                loading={diffLoading}
                highlight={highlightBeliefRevision}
                proofChain={proofChain}
                memoryReceiptIds={beliefRevisionMemoryIds}
                onOpenEvidence={openEvidenceDrawer}
                onOpenMemory={(memoryId) => {
                  const episode = episodicMemoryById.get(memoryId);
                  if (episode) {
                    openEpisodicTimelineMemory(episode);
                    return;
                  }
                  if (memoryId === profileMemoryId) {
                    openProfileMemory();
                  }
                }}
              />
            </div>
            <div
              id="section-evidence"
              className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-2"
            >
              <EvidenceSpotlight
                activeQuarter={activeQuarter}
                drugId={selectedDrugId}
                evidence={autoEvidenceResponse?.evidence ?? []}
                signalSnapshot={signalSnapshot}
                scorecard={scorecardAsOfViewed}
                topSignal={topSignal}
                reinterpretedReportIds={
                  autoReinterpretedReportIds.length > 0
                    ? autoReinterpretedReportIds
                    : (beliefDiff?.reinterpreted_report_ids ?? [])
                }
                onOpenEvidence={openEvidenceDrawer}
                onOpenEventLogMemory={openEventLogMemory}
                showMemorySources={showMemorySources}
                loading={autoEvidenceLoading}
                emptyMessage={
                  autoEvidenceError ??
                  "No report-level evidence found for this quarter yet."
                }
                focusEvent={autoFocusEvent}
              />
              <PredictionScorecard
                entries={displayedScorecard}
                loading={loading}
                asOfQuarter={scorecardQuarterLabel}
                hiddenFutureCount={displayedHiddenFuturePredictionsCount}
                showMemorySources={showMemorySources}
                onOpenForesightMemory={openForesightMemory}
                demoStage={demoStage}
                presentationMode={scorecardPresentationMode}
                receiptSummary={casefileSummary?.receipt_summary ?? null}
                watchlistSummary={
                  casefileSummary &&
                  (casefileSummary.watchlist_alerts.length > 0 ||
                    casefileSummary.key_label_gaps.length > 0)
                    ? `${casefileSummary.watchlist_alerts.length} watchlist alert${
                        casefileSummary.watchlist_alerts.length === 1 ? "" : "s"
                      } and ${casefileSummary.key_label_gaps.length} label-gap cue${
                        casefileSummary.key_label_gaps.length === 1 ? "" : "s"
                      } are active in the casefile header.`
                    : null
                }
              />
            </div>

            <section className="mt-5">
              <MemoryArchitectureCard
                totalReports={totalReportsLoadedDisplay}
                episodicCount={episodes.length}
                profileUpdated={profile !== null}
                foresightCount={scorecard.length}
                evermemosOk={evermemosOk === true}
                onOpenMemoryType={(type) => {
                  if (type === "Profile") {
                    openProfileMemory();
                  } else if (type === "Foresight" && scorecard.length > 0) {
                    openForesightMemory(
                      scorecard[0],
                      buildForesightMemoryId(
                        selectedDrugId,
                        scorecard[0].prediction.adverse_event,
                      ),
                    );
                  }
                }}
              />
            </section>

            <section id="section-signals" className="mt-5">
              {loading ? (
                <div className={`h-[460px] ${shimmerClass()}`} />
              ) : (
                <SignalTimeline
                  points={timelineAsOfViewed}
                  fdaActions={fdaActions}
                  predictionEntries={scorecard}
                  selectedEvents={suggestedEvents}
                  onToggleEvent={toggleEvent}
                  activeQuarter={chartQuarterLabel}
                  reinterpretationMarkers={reinterpretationMarkers}
                />
              )}
            </section>

            {showAnalystWorkspaceToggle ? (
              <section
                id="section-analyst"
                ref={analystWorkspaceSectionRef}
                className="mt-8 overflow-hidden rounded-[1.35rem] border border-white/[0.06] bg-[var(--bg-panel)]"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] bg-[linear-gradient(90deg,rgba(212,149,106,0.06),transparent)] px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent-dim)] text-[var(--accent)]">
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <circle cx="8" cy="5" r="3" />
                        <path d="M2 15v-1a5 5 0 0110 0v1" />
                        <path d="M12 5h3M13.5 3.5v3" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-[var(--text-primary)]">
                        Analyst Workspace
                      </p>
                      <p className="text-[11px] text-[var(--text-secondary)]">
                        Drug selection, ingestion controls, and deep reasoning
                        tools
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={
                      analystWorkspaceOpen
                        ? handleCloseAnalystWorkspace
                        : handleOpenAnalystWorkspace
                    }
                    className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3.5 py-2 text-xs font-semibold text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                  >
                    {analystWorkspaceOpen ? "Hide workspace" : "Open workspace"}
                  </button>
                </div>
              </section>
            ) : null}

            {analystWorkspaceOpen ? (
              <section className="mt-1 overflow-hidden rounded-b-[1.35rem] border border-t-0 border-white/[0.06] bg-[var(--bg-panel)] p-5">
                <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
                  <section className="space-y-4 lg:col-span-3">
                    <DrugSelector
                      drugs={drugs}
                      selectedDrugId={selectedDrugId}
                      loading={loading && drugs.length === 0}
                      onSelect={(id) => {
                        cancelDemoRun();
                        setIsPlaying(false);
                        setBeliefDiff(null);
                        clearTimeTravelCaches();
                        setQueryResponse(null);
                        clearAutoEvidenceCaches();
                        setReinterpretationMarkers([]);
                        setSignalToasts([]);
                        setForcedBeliefTab(null);
                        clearThoughtTimers();
                        seenThoughtIdsRef.current.clear();
                        thoughtQuarterRef.current = null;
                        lastSyntheticSummaryQuarterRef.current = null;
                        lastSyntheticObservationQuarterRef.current = null;
                        setAgentLog([]);
                        setAgentRunState("idle");
                        setIngestProgress(null);
                        setFastDemoReady(false);
                        setShowMemorySources(false);
                        setDemoStage("analyst");
                        setSelectedDrugId(id);
                        navigate(`/casefile/${id}`);
                      }}
                    />
                    <IngestButton
                      status={ingestStatus}
                      storedReportCount={selectedDrug?.total_reports ?? 0}
                      onIngest={handleIngest}
                      onIngestAll={handleIngestAll}
                      onCancelIngestAll={handleCancelIngestAll}
                      onRebuildFullHistory={handleRebuildFullHistory}
                      onDismissFullHistory={handleDismissRebuildStatus}
                      onReset={handleReset}
                      progress={ingestProgress}
                      ingestAllProgress={ingestAllProgress}
                      fullHistoryJob={rebuildJob}
                      fullHistoryLoading={
                        rebuildJobLoading || creatingRebuildJob
                      }
                      fullHistoryError={rebuildJobError}
                    />
                    <ProfileCard
                      profile={profile}
                      loading={loading}
                      totalReportsAnalyzed={totalReportsLoadedDisplay}
                      quartersAnalyzed={quartersLoadedCountDisplay}
                      showMemorySources={showMemorySources}
                      memoryUpdatedQuarter={activeQuarter}
                      memoryId={profileMemoryId}
                      onOpenMemory={openProfileMemory}
                    />
                  </section>

                  <section className="space-y-4 lg:col-span-4">
                    <AboutPanel
                      reportsLoaded={totalReportsLoadedDisplay}
                      quartersLoaded={quartersLoadedCountDisplay}
                      beliefCount={beliefs.length}
                      scorecardSummary={scorecardSummary}
                      drugLabel={selectedDrug?.generic_name ?? selectedDrugId}
                      isPrimaryDemoDrug={isPrimaryDemoDrug}
                    />
                    <MemoryProvenance
                      enabled={showMemorySources}
                      onToggle={() =>
                        setShowMemorySources((current) => !current)
                      }
                      memoryStatusLabel={memoryStatus.label}
                      memoryStatusTone={memoryStatus.tone}
                      foresightStatus={foresightStatus}
                    />
                  </section>

                  <section className="space-y-4 lg:col-span-5">
                    <section className="rounded-xl border border-white/[0.06] bg-[var(--bg-card)] p-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[rgba(139,92,246,0.12)] text-[#8b5cf6]">
                            <svg
                              width="16"
                              height="16"
                              viewBox="0 0 16 16"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M8 2v4l3 2" />
                              <circle cx="8" cy="8" r="6" />
                            </svg>
                          </div>
                          <div>
                            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                              Agent Reasoning
                            </h2>
                            <p className="text-[11px] text-[var(--text-secondary)]">
                              Thought stream, memory loop, and reasoning
                              receipts
                            </p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setDrawerOpen((current) => !current)}
                          className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                        >
                          {drawerOpen ? "Collapse" : "Expand"}
                        </button>
                      </div>

                      {drawerOpen ? (
                        <div className="mt-4 space-y-4">
                          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                            <AgentThoughtStream
                              entries={agentLog}
                              runState={agentRunState}
                              showMemorySources={showMemorySources}
                              idleHint="Agent ready. Run the staged demo or use the analyst controls below to inspect the current quarter."
                              onOpenMemoryRef={openThoughtMemoryRef}
                            />
                            <MemoryReasoningLoopTrace
                              quarter={activeQuarter}
                              memoryStep={loopTraceSteps.memory}
                              reasoningStep={loopTraceSteps.reasoning}
                              actionStep={loopTraceSteps.action}
                            />
                          </div>
                          <div className="flex gap-1 border-b border-[var(--border)] pb-3">
                            {drawerTabs.map((tab) => (
                              <button
                                key={tab.key}
                                type="button"
                                onClick={() =>
                                  setDrawerTab(
                                    tab.key as
                                      | "belief"
                                      | "episodic"
                                      | "query"
                                      | "all",
                                  )
                                }
                                className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                                  drawerTab === tab.key
                                    ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-white/[0.04]"
                                }`}
                              >
                                {tab.label}
                              </button>
                            ))}
                          </div>

                          {drawerTab === "query" || drawerTab === "all" ? (
                            <QueryInterface
                              drugId={selectedDrugId}
                              activeQuarter={activeQuarter}
                              onSubmit={handleQuery}
                              response={queryResponse}
                              loading={queryLoading}
                              onOpenEvidence={openEvidenceDrawer}
                            />
                          ) : null}
                          {drawerTab === "episodic" || drawerTab === "all" ? (
                            <EpisodicTimeline
                              episodes={episodes}
                              loading={loading}
                              showMemorySources={showMemorySources}
                              currentQuarter={activeQuarter}
                              onOpenMemory={openEpisodicTimelineMemory}
                            />
                          ) : null}
                          {drawerTab === "belief" || drawerTab === "all" ? (
                            <BeliefDiff
                              beliefs={beliefs}
                              diff={beliefDiff}
                              loading={diffLoading}
                              currentQuarter={activeQuarter}
                              onRequestDiff={handleRequestDiff}
                              onOpenEvidence={openEvidenceDrawer}
                            />
                          ) : null}
                        </div>
                      ) : null}
                    </section>
                  </section>
                </div>
              </section>
            ) : null}
          </>
        )}
      </main>
      <SignalAlertToast toasts={signalToasts} />

      <MemoryViewerModal
        open={memoryViewerOpen}
        entry={memoryViewerEntry}
        drugId={selectedDrugId}
        onClose={closeMemoryViewer}
      />

      <EvidenceDrawer
        open={evidenceDrawerOpen}
        reportId={evidenceReportId}
        initialReport={
          evidenceReportId ? evidenceReportCache[evidenceReportId] ?? null : null
        }
        onClose={closeEvidenceDrawer}
        onLoaded={handleEvidenceDrawerLoaded}
      />

      <footer className="border-t border-white/[0.04] bg-[var(--bg-panel)]/50 py-4 text-center">
        <p className="text-[11px] text-[var(--text-tertiary)]">
          <span className="font-semibold text-[var(--accent)]">VigiLens</span>{" "}
          &middot; Memory-native pharmacovigilance &middot; Built for Memory
          Genesis 2026
        </p>
      </footer>
    </div>
  );
}
