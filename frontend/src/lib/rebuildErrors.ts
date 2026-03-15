import { ApiError } from "../api/client";

const ROUTE_NOT_FOUND_DETAIL = "Not Found";
const TRACKING_JOB_NOT_FOUND_DETAIL = "Tracking job was not found.";

export function getRebuildStartErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.statusCode === 404) {
    const detail = error.payload?.detail ?? error.message;
    if (detail === ROUTE_NOT_FOUND_DETAIL) {
      return "Full-history rebuild is unavailable on the running backend. Restart the backend server and try again.";
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "Full-history rebuild failed to start";
}

export function getRebuildPollError(error: unknown): { message: string; clearPersistedJob: boolean } {
  if (error instanceof ApiError && error.statusCode === 404) {
    const detail = error.payload?.detail ?? error.message;
    if (detail === TRACKING_JOB_NOT_FOUND_DETAIL) {
      return {
        message: "Saved rebuild status was not found. Start the rebuild again.",
        clearPersistedJob: true,
      };
    }
    if (detail === ROUTE_NOT_FOUND_DETAIL) {
      return {
        message: "Full-history rebuild is unavailable on the running backend. Restart the backend server and try again.",
        clearPersistedJob: false,
      };
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return { message: error.message, clearPersistedJob: false };
  }

  return { message: "Full-history rebuild unavailable", clearPersistedJob: false };
}
