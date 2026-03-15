const REBUILD_JOB_STORAGE_PREFIX = "vigilens:rebuild-job:";

function storageKey(drugId: string): string {
  return `${REBUILD_JOB_STORAGE_PREFIX}${drugId}`;
}

export function readPersistedRebuildJobId(drugId: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const value = window.sessionStorage.getItem(storageKey(drugId));
  const trimmed = value?.trim() ?? "";
  return trimmed || null;
}

export function persistRebuildJobId(drugId: string, jobId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const trimmed = jobId.trim();
  if (!trimmed) {
    return;
  }
  window.sessionStorage.setItem(storageKey(drugId), trimmed);
}

export function clearPersistedRebuildJobId(drugId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(storageKey(drugId));
}
