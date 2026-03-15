import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  deleteDrug,
  getCatalogPreview,
  getCatalogSearch,
  getDrugs,
  getTrackingJob,
  postTrackingJob,
} from "../api/client";
import { DrugPreviewPanel, type MonitoringOptions } from "../components/DrugPreviewPanel";
import { DrugSearchBar } from "../components/DrugSearchBar";
import { DrugSearchResults } from "../components/DrugSearchResults";
import { TrackingProgress } from "../components/TrackingProgress";
import { TrackedDrugList } from "../components/TrackedDrugList";
import { useVigilensStore } from "../store/useVigilensStore";
import type { CatalogPreviewResponse, CatalogSearchResult, TrackingJob } from "../types/shared";

const DEFAULT_MONITORING_OPTIONS: MonitoringOptions = {
  baselineQuarters: 4,
  maxReports: 1500,
  preferCached: true,
};

function trimSearch(value: string): string {
  return value.trim();
}

interface ParamUpdates {
  q?: string | null;
  candidate?: string | null;
  job?: string | null;
}

export function Discover() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const drugs = useVigilensStore((state) => state.drugs);
  const selectedDrugId = useVigilensStore((state) => state.selectedDrugId);
  const setDrugs = useVigilensStore((state) => state.setDrugs);
  const setSelectedDrugId = useVigilensStore((state) => state.setSelectedDrugId);
  const clearDrugScopedData = useVigilensStore((state) => state.clearDrugScopedData);

  const [results, setResults] = useState<CatalogSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CatalogPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [trackedLoading, setTrackedLoading] = useState(false);
  const [monitoringOptions, setMonitoringOptions] = useState<MonitoringOptions>(DEFAULT_MONITORING_OPTIONS);
  const [trackingJob, setTrackingJob] = useState<TrackingJob | null>(null);
  const [trackingJobLoading, setTrackingJobLoading] = useState(false);
  const [trackingJobError, setTrackingJobError] = useState<string | null>(null);
  const [creatingJob, setCreatingJob] = useState(false);
  const [deletingDrugId, setDeletingDrugId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const searchControllerRef = useRef<AbortController | null>(null);
  const previewControllerRef = useRef<AbortController | null>(null);
  const redirectingJobIdRef = useRef<string | null>(null);
  const pollingInFlightRef = useRef(false);

  const query = searchParams.get("q") ?? "";
  const candidateName = searchParams.get("candidate");
  const jobId = searchParams.get("job");
  const trackingBusy =
    creatingJob || (jobId !== null && trackingJobError === null && trackingJob?.status !== "failed");

  const updateParams = useCallback(
    (updates: ParamUpdates) => {
      const params = new URLSearchParams(searchParams);
      if (updates.q !== undefined) {
        const next = trimSearch(updates.q ?? "");
        if (next) {
          params.set("q", next);
        } else {
          params.delete("q");
        }
      }
      if (updates.candidate !== undefined) {
        const next = trimSearch(updates.candidate ?? "");
        if (next) {
          params.set("candidate", next);
        } else {
          params.delete("candidate");
        }
      }
      if (updates.job !== undefined) {
        const next = trimSearch(updates.job ?? "");
        if (next) {
          params.set("job", next);
        } else {
          params.delete("job");
        }
      }
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const refreshTrackedDrugs = useCallback(async () => {
    setTrackedLoading(true);
    try {
      const nextDrugs = await getDrugs();
      setDrugs(nextDrugs);
      return nextDrugs;
    } finally {
      setTrackedLoading(false);
    }
  }, [setDrugs]);

  useEffect(() => {
    void refreshTrackedDrugs();
  }, [refreshTrackedDrugs]);

  useEffect(() => {
    const trimmed = trimSearch(query);
    searchControllerRef.current?.abort();

    if (trimmed.length < 2) {
      setResults([]);
      setSearchLoading(false);
      setSearchError(null);
      return;
    }

    const controller = new AbortController();
    searchControllerRef.current = controller;
    setSearchLoading(true);
    setSearchError(null);

    void getCatalogSearch(trimmed, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setResults(payload);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setSearchError(error instanceof Error ? error.message : "Search failed");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setSearchLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    previewControllerRef.current?.abort();

    if (!candidateName) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }

    const controller = new AbortController();
    previewControllerRef.current = controller;
    setPreviewLoading(true);
    setPreviewError(null);

    void getCatalogPreview(candidateName, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setPreview(payload);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setPreview(null);
          setPreviewError(error instanceof Error ? error.message : "Preview failed");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setPreviewLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [candidateName]);

  useEffect(() => {
    if (!jobId) {
      setTrackingJob(null);
      setTrackingJobError(null);
      setTrackingJobLoading(false);
      setCreatingJob(false);
      pollingInFlightRef.current = false;
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    const loadJob = async () => {
      if (pollingInFlightRef.current) {
        return;
      }
      pollingInFlightRef.current = true;
      try {
        setTrackingJobLoading(true);
        const payload = await getTrackingJob(jobId, controller.signal);
        if (!cancelled) {
          setTrackingJob(payload);
          setTrackingJobError(null);
          setCreatingJob(false);
        }
      } catch (error) {
        if (!cancelled && !(error instanceof Error && error.name === "AbortError")) {
          setTrackingJobError(error instanceof Error ? error.message : "Tracking job unavailable");
          setCreatingJob(false);
        }
      } finally {
        if (!cancelled) {
          setTrackingJobLoading(false);
        }
        pollingInFlightRef.current = false;
      }
    };

    void loadJob();
    const poll = window.setInterval(() => {
      if (trackingJob?.status === "ready" || trackingJob?.status === "failed") {
        return;
      }
      void loadJob();
    }, 1000);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(poll);
    };
  }, [jobId, trackingJob?.status]);

  useEffect(() => {
    if (!trackingJob || trackingJob.status !== "ready" || !trackingJob.drug_id) {
      return;
    }
    if (redirectingJobIdRef.current === trackingJob.id) {
      return;
    }
    const resolvedDrugId = trackingJob.drug_id;
    redirectingJobIdRef.current = trackingJob.id;

    let cancelled = false;
    void (async () => {
      const nextDrugs = await refreshTrackedDrugs();
      if (cancelled) {
        return;
      }
      if (!nextDrugs.some((drug) => drug.id === resolvedDrugId)) {
        await refreshTrackedDrugs();
        if (cancelled) {
          return;
        }
      }
      setSelectedDrugId(resolvedDrugId);
      navigate(`/casefile/${resolvedDrugId}`, { replace: true });
    })();

    return () => {
      cancelled = true;
    };
  }, [navigate, refreshTrackedDrugs, setSelectedDrugId, trackingJob]);

  const handleDebouncedChange = useCallback(
    (value: string) => {
      const trimmed = trimSearch(value);
      const nextCandidate = trimmed && trimmed === query ? candidateName : null;
      updateParams({ q: trimmed || null, candidate: nextCandidate });
      if (!trimmed) {
        setPreview(null);
        setPreviewError(null);
        setTrackingJobError(null);
      }
    },
    [candidateName, query, updateParams],
  );

  const handleSubmit = useCallback(
    (value: string) => {
      const trimmed = trimSearch(value);
      const nextCandidate = trimmed && trimmed === query ? candidateName : null;
      updateParams({ q: trimmed || null, candidate: nextCandidate });
    },
    [candidateName, query, updateParams],
  );

  const handleSelectCandidate = useCallback(
    (genericName: string) => {
      updateParams({ candidate: genericName });
      setTrackingJobError(null);
    },
    [updateParams],
  );

  const openCasefile = useCallback(
    (drugId: string) => {
      setSelectedDrugId(drugId);
      navigate(`/casefile/${drugId}`);
    },
    [navigate, setSelectedDrugId],
  );

  const startMonitoring = useCallback(
    async (medicationName: string, options: MonitoringOptions) => {
      if (trackingBusy) {
        return;
      }

      setCreatingJob(true);
      setTrackingJobError(null);
      try {
        const job = await postTrackingJob({
          medicationName,
          baselineQuarters: options.baselineQuarters,
          maxReports: options.maxReports,
          preferCached: options.preferCached,
        });
        setTrackingJob(job);
        updateParams({
          candidate: preview?.generic_name ?? medicationName,
          job: job.id,
        });
      } catch (error) {
        setTrackingJobError(error instanceof Error ? error.message : "Tracking job failed to start");
        setCreatingJob(false);
      }
    },
    [preview?.generic_name, trackingBusy, updateParams],
  );

  const handlePreviewStart = useCallback(async () => {
    const targetName = preview?.generic_name ?? candidateName;
    if (!targetName) {
      return;
    }
    await startMonitoring(targetName, monitoringOptions);
  }, [candidateName, monitoringOptions, preview?.generic_name, startMonitoring]);

  const handleQuickStart = useCallback(
    async (genericName: string) => {
      handleSelectCandidate(genericName);
      await startMonitoring(genericName, DEFAULT_MONITORING_OPTIONS);
    },
    [handleSelectCandidate, startMonitoring],
  );

  const handleDismissTracking = useCallback(() => {
    setTrackingJob(null);
    setTrackingJobError(null);
    setCreatingJob(false);
    updateParams({ job: null });
  }, [updateParams]);

  const handleDeleteDrug = useCallback(
    async (drugId: string) => {
      setDeletingDrugId(drugId);
      setDeleteError(null);

      try {
        await deleteDrug(drugId);
        const nextDrugs = await refreshTrackedDrugs();

        if (selectedDrugId === drugId) {
          const fallbackDrugId = nextDrugs[0]?.id;
          if (fallbackDrugId) {
            setSelectedDrugId(fallbackDrugId);
          } else {
            clearDrugScopedData();
          }
        }

        if (candidateName) {
          try {
            const refreshedPreview = await getCatalogPreview(candidateName);
            setPreview(refreshedPreview);
            setPreviewError(null);
          } catch (error) {
            setPreview(null);
            setPreviewError(error instanceof Error ? error.message : "Preview failed");
          }
        }

        return true;
      } catch (error) {
        setDeleteError(error instanceof Error ? error.message : "Delete failed");
        return false;
      } finally {
        setDeletingDrugId(null);
      }
    },
    [candidateName, clearDrugScopedData, refreshTrackedDrugs, selectedDrugId, setSelectedDrugId],
  );

  return (
    <main className="mx-auto flex w-full max-w-[1680px] flex-col gap-6 px-4 pb-10 pt-24 sm:px-6 lg:px-8">
      <DrugSearchBar
        initialValue={query}
        loading={searchLoading}
        onDebouncedChange={handleDebouncedChange}
        onSubmit={handleSubmit}
      />

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_380px]">
        <TrackedDrugList
          drugs={drugs}
          selectedDrugId={selectedDrugId || null}
          loading={trackedLoading}
          deletingDrugId={deletingDrugId}
          error={deleteError}
          onOpen={openCasefile}
          onDelete={handleDeleteDrug}
        />

        <DrugSearchResults
          results={results}
          query={query}
          selectedGenericName={candidateName}
          loading={searchLoading}
          error={searchError}
          onSelect={handleSelectCandidate}
          onOpenCasefile={openCasefile}
          onQuickStart={handleQuickStart}
          onboarding={trackingBusy}
        />

        <div className="xl:sticky xl:top-24 xl:self-start">
          {jobId || creatingJob ? (
            <TrackingProgress
              job={trackingJob}
              loading={trackingJobLoading || creatingJob}
              error={trackingJobError}
              onDismiss={handleDismissTracking}
            />
          ) : (
            <>
              <DrugPreviewPanel
                preview={preview}
                candidateName={candidateName}
                options={monitoringOptions}
                loading={previewLoading}
                error={previewError}
                onboarding={trackingBusy}
                onboardingMessage={null}
                onChangeOptions={setMonitoringOptions}
                onStartMonitoring={handlePreviewStart}
                onOpenCasefile={openCasefile}
              />
              {trackingJobError ? (
                <div className="mt-3 rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                  {trackingJobError}
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
