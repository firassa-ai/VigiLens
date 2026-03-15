import { create } from "zustand";

import type {
  Belief,
  BeliefDiff,
  Drug,
  DrugProfile,
  EpisodicSummary,
  FAERSReport,
  FDAAction,
  IngestProgressMessage,
  IngestStatus,
  QueryResponse,
  ScorecardEntry,
  SignalPoint,
  SituationAnalysis,
} from "../types/shared";

export interface VigilensState {
  selectedDrugId: string;

  drugs: Drug[];
  ingestStatus: IngestStatus | null;
  ingestProgress: IngestProgressMessage | null;

  timelinePoints: SignalPoint[];
  activeSignals: SignalPoint[];
  profile: DrugProfile | null;
  episodes: EpisodicSummary[];
  fdaActions: FDAAction[];
  beliefs: Belief[];
  beliefDiff: BeliefDiff | null;
  scorecard: ScorecardEntry[];

  queryResponse: QueryResponse | null;

  situationAnalysis: SituationAnalysis | null;
  situationLoading: boolean;

  evidenceDrawerOpen: boolean;
  evidenceReportId: string | null;
  evidenceReport: FAERSReport | null;

  setSelectedDrugId: (id: string) => void;
  setDrugs: (drugs: Drug[]) => void;
  setIngestProgress: (p: IngestProgressMessage | null) => void;
  setIngestStatus: (status: IngestStatus | null) => void;
  setTimelinePoints: (points: SignalPoint[]) => void;
  setActiveSignals: (points: SignalPoint[]) => void;
  setProfile: (profile: DrugProfile | null) => void;
  setEpisodes: (episodes: EpisodicSummary[]) => void;
  setFdaActions: (actions: FDAAction[]) => void;
  setBeliefs: (beliefs: Belief[]) => void;
  setBeliefDiff: (diff: BeliefDiff | null) => void;
  setScorecard: (entries: ScorecardEntry[]) => void;
  setQueryResponse: (response: QueryResponse | null) => void;
  setSituationAnalysis: (analysis: SituationAnalysis | null) => void;
  setSituationLoading: (loading: boolean) => void;
  openEvidenceDrawer: (reportId: string) => void;
  setEvidenceReport: (report: FAERSReport | null) => void;
  closeEvidenceDrawer: () => void;
  clearDrugScopedData: () => void;
}

const initialSelectedDrug = "semaglutide";

export const useVigilensStore = create<VigilensState>((set) => ({
  selectedDrugId: initialSelectedDrug,

  drugs: [],
  ingestStatus: null,
  ingestProgress: null,

  timelinePoints: [],
  activeSignals: [],
  profile: null,
  episodes: [],
  fdaActions: [],
  beliefs: [],
  beliefDiff: null,
  scorecard: [],

  queryResponse: null,

  situationAnalysis: null,
  situationLoading: false,

  evidenceDrawerOpen: false,
  evidenceReportId: null,
  evidenceReport: null,

  setSelectedDrugId: (id) =>
    set((state) => {
      if (state.selectedDrugId === id) {
        return state;
      }
      return {
        selectedDrugId: id,
        ingestStatus: null,
        ingestProgress: null,
        timelinePoints: [],
        activeSignals: [],
        profile: null,
        episodes: [],
        fdaActions: [],
        beliefs: [],
        beliefDiff: null,
        scorecard: [],
        queryResponse: null,
        situationAnalysis: null,
        situationLoading: false,
        evidenceDrawerOpen: false,
        evidenceReport: null,
        evidenceReportId: null,
      };
    }),
  setDrugs: (drugs) => set({ drugs }),
  setIngestProgress: (p) => set({ ingestProgress: p }),
  setIngestStatus: (status) => set({ ingestStatus: status }),
  setTimelinePoints: (points) => set({ timelinePoints: points }),
  setActiveSignals: (points) => set({ activeSignals: points }),
  setProfile: (profile) => set({ profile }),
  setEpisodes: (episodes) => set({ episodes }),
  setFdaActions: (actions) => set({ fdaActions: actions }),
  setBeliefs: (beliefs) => set({ beliefs }),
  setBeliefDiff: (diff) => set({ beliefDiff: diff }),
  setScorecard: (entries) => set({ scorecard: entries }),
  setQueryResponse: (response) => set({ queryResponse: response }),
  setSituationAnalysis: (analysis) => set({ situationAnalysis: analysis }),
  setSituationLoading: (loading) => set({ situationLoading: loading }),
  openEvidenceDrawer: (reportId) =>
    set({
      evidenceDrawerOpen: true,
      evidenceReportId: reportId,
      evidenceReport: null,
    }),
  setEvidenceReport: (report) => set({ evidenceReport: report }),
  closeEvidenceDrawer: () =>
    set({
      evidenceDrawerOpen: false,
      evidenceReportId: null,
      evidenceReport: null,
    }),
  clearDrugScopedData: () =>
    set({
      ingestStatus: null,
      ingestProgress: null,
      timelinePoints: [],
      activeSignals: [],
      profile: null,
      episodes: [],
      fdaActions: [],
      beliefs: [],
      beliefDiff: null,
      scorecard: [],
      queryResponse: null,
      situationAnalysis: null,
      situationLoading: false,
      evidenceDrawerOpen: false,
      evidenceReportId: null,
      evidenceReport: null,
    }),
}));
