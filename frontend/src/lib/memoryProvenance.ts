export type MemoryClass = "Episodic" | "Profile" | "Foresight" | "EventLog";

function quarterToken(quarter: string | null | undefined): string {
  const cleaned = (quarter ?? "").trim();
  if (!cleaned) {
    return "latest";
  }
  return cleaned.replaceAll("-", "");
}

export function buildProfileMemoryId(drugId: string, quarter: string | null | undefined): string {
  return `vigl_${drugId}_${quarterToken(quarter)}_profile`;
}

export function buildForesightMemoryId(drugId: string, quarter: string | null | undefined): string {
  return `vigl_${drugId}_${quarterToken(quarter)}_foresight`;
}

export function buildEventLogMemoryId(
  drugId: string,
  reportId: string,
): string {
  return `vigl_${drugId}_${reportId}_eventlog`;
}
