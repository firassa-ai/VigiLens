import { useEffect, useState } from "react";

import { getMemoryProxy } from "../api/client";
import type { MemoryClass } from "../lib/memoryProvenance";
import type { MemoryProxyResponse } from "../types/shared";

export interface MemoryViewerEntry {
  id: string;
  type: MemoryClass;
  label?: string;
  quarter: string | null;
  narrative: string;
  source: string;
  whyUsed?: string;
  metadata?: Array<{ label: string; value: string }>;
}

export interface MemoryViewerModalProps {
  open: boolean;
  entry: MemoryViewerEntry | null;
  drugId?: string;
  onClose: () => void;
}

type MemoryViewerTab = "summary" | "raw";

function truncateRawValue(value: unknown, depth = 0): unknown {
  if (depth >= 5) {
    return "[Max depth reached]";
  }
  if (typeof value === "string") {
    return value.length > 400 ? `${value.slice(0, 400)}... [truncated]` : value;
  }
  if (Array.isArray(value)) {
    const maxItems = 40;
    const trimmed = value.slice(0, maxItems).map((item) => truncateRawValue(item, depth + 1));
    if (value.length > maxItems) {
      trimmed.push(`... [${value.length - maxItems} more items]`);
    }
    return trimmed;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const maxKeys = 60;
    const trimmedEntries = entries.slice(0, maxKeys).map(([key, item]) => [key, truncateRawValue(item, depth + 1)]);
    if (entries.length > maxKeys) {
      trimmedEntries.push(["__truncated__", `[${entries.length - maxKeys} more keys]`]);
    }
    return Object.fromEntries(trimmedEntries);
  }
  return value;
}

export function MemoryViewerModal({
  open,
  entry,
  drugId,
  onClose,
}: MemoryViewerModalProps) {
  const [activeTab, setActiveTab] = useState<MemoryViewerTab>("summary");
  const [rawMemory, setRawMemory] = useState<MemoryProxyResponse | null>(null);
  const [rawLoading, setRawLoading] = useState(false);
  const [rawError, setRawError] = useState<string | null>(null);

  useEffect(() => {
    setActiveTab("summary");
  }, [entry?.id, open]);

  useEffect(() => {
    if (!open || !entry || !drugId) {
      setRawMemory(null);
      setRawLoading(false);
      setRawError(null);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      setRawLoading(true);
      setRawError(null);
      try {
        const payload = await getMemoryProxy(drugId, entry.id, false, controller.signal);
        if (cancelled) {
          return;
        }
        setRawMemory(payload);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message = error instanceof Error ? error.message : "Failed to load raw memory payload.";
        setRawError(message);
      } finally {
        if (!cancelled) {
          setRawLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [drugId, entry, open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [onClose, open]);

  if (!open || !entry) {
    return null;
  }

  const rawPreview = rawMemory ? JSON.stringify(truncateRawValue(rawMemory.payload), null, 2) : "";

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/60" onClick={onClose} />
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Memory Viewer"
        className="fixed inset-x-4 top-1/2 z-50 mx-auto w-full max-w-2xl -translate-y-1/2 rounded-xl border border-[var(--border)] bg-[var(--bg-root)] p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium tracking-wide text-[var(--text-tertiary)]">Memory Viewer</p>
            <h3 className="mt-1 font-display text-lg text-[var(--text-primary)]">
              {entry.label ?? `${entry.type} Memory`}
            </h3>
            <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
              EverMemOS hierarchy: ingested messages -&gt; MemCell extraction -&gt; MemScene consolidation. `group_id` is the per-drug isolation namespace, not the memory object itself.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.08]"
          >
            Close
          </button>
        </div>

        <div className="mb-3 flex gap-1 border-b border-[var(--border)] pb-3">
          <button
            type="button"
            onClick={() => setActiveTab("summary")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
              activeTab === "summary"
                ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:bg-white/[0.04] hover:text-[var(--text-primary)]"
            }`}
          >
            Summary
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("raw")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
              activeTab === "raw"
                ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:bg-white/[0.04] hover:text-[var(--text-primary)]"
            }`}
          >
            Raw EverMemOS Object
          </button>
        </div>

        {activeTab === "summary" ? (
        <div className="space-y-3 text-sm">
          {entry.whyUsed ? (
            <div className="rounded-lg border border-[var(--accent-border)] bg-[var(--accent-dim)] p-3">
              <p className="text-xs font-medium text-[var(--accent)]">Why was this memory used?</p>
              <p className="mt-1 leading-relaxed text-[var(--text-secondary)]">{entry.whyUsed}</p>
            </div>
          ) : null}
          <div className="rounded-lg bg-[var(--bg-panel)] p-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Memory Label</p>
            <p className="mt-1 text-[var(--text-secondary)]">{entry.label ?? `${entry.type} Memory`}</p>
            <p className="mt-2 text-[11px] text-[var(--text-tertiary)]">ID: <span className="break-all font-mono">{entry.id}</span></p>
          </div>
          <div className="rounded-lg bg-[var(--bg-panel)] p-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Quarter</p>
            <p className="mt-1 text-[var(--text-secondary)]">{entry.quarter ?? "-"}</p>
          </div>
          <div className="rounded-lg bg-[var(--bg-panel)] p-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Narrative</p>
            <p className="mt-1 whitespace-pre-wrap leading-relaxed text-[var(--text-secondary)]">
              {entry.narrative}
            </p>
          </div>
          <div className="rounded-lg bg-[var(--bg-panel)] p-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Source</p>
            <p className="mt-1 text-[var(--text-secondary)]">{entry.source}</p>
          </div>
          {entry.metadata && entry.metadata.length > 0 ? (
            <div className="rounded-lg bg-[var(--bg-panel)] p-3">
              <p className="text-xs font-medium text-[var(--text-tertiary)]">Metadata</p>
              <div className="mt-1 space-y-1">
                {entry.metadata.map((item) => (
                  <p key={`${item.label}:${item.value}`} className="text-xs text-[var(--text-secondary)]">
                    <span className="font-medium text-[var(--text-primary)]">{item.label}:</span> {item.value}
                  </p>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        ) : (
          <div className="space-y-3 text-sm">
            {rawLoading ? (
              <div className="rounded-lg bg-[var(--bg-panel)] p-3 text-[var(--text-secondary)]">
                Loading cached raw memory payload...
              </div>
            ) : null}
            {!rawLoading && rawError ? (
              <div className="rounded-lg border border-amber-500/20 bg-[var(--warning-dim)] p-3 text-amber-200">
                {rawError}
              </div>
            ) : null}
            {!rawLoading && !rawError && rawMemory ? (
              <>
                <div className="rounded-lg bg-[var(--bg-panel)] p-3">
                  <p className="text-xs font-medium text-[var(--text-tertiary)]">Cache Metadata</p>
                  <div className="mt-1 space-y-1">
                    <p className="text-xs text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">Memory type:</span> {rawMemory.memory_type ?? "-"}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">group_id:</span> {rawMemory.group_id ?? "-"}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">Quarter:</span> {rawMemory.quarter ?? "-"}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">Source endpoint:</span> {rawMemory.source_endpoint ?? "-"}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">Cache-first:</span> {rawMemory.cached ? "yes" : "no"}
                    </p>
                  </div>
                </div>
                <div className="rounded-lg bg-[var(--bg-panel)] p-3">
                  <p className="text-xs font-medium text-[var(--text-tertiary)]">Raw payload (sanitized preview)</p>
                  <pre className="mt-2 max-h-[320px] overflow-auto whitespace-pre-wrap break-all rounded bg-black/20 p-2 font-mono text-[11px] text-[var(--text-secondary)]">
                    {rawPreview}
                  </pre>
                </div>
              </>
            ) : null}
          </div>
        )}
      </section>
    </>
  );
}
