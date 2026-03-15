import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const thisDir = dirname(fileURLToPath(import.meta.url));

describe("Dashboard static copy guard", () => {
  it("does not include deprecated dashboard explainer heading", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).not.toContain("How to read this dashboard");
  });

  it("keeps the staged reveal flow and avoids auto-enabling provenance", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain('const FAST_DEMO_QUARTER = "2023-Q2"');
    expect(source).toContain('const REVEAL_QUARTER = "2023-Q3"');
    expect(source).toContain('const VALIDATION_QUARTER = "2023-Q4"');
    expect(source).not.toContain("setShowMemorySources(true)");
  });

  it("keeps Time Travel in the main stack instead of analyst mode only", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain("const timeTravelExplorer = (");
    expect(source.indexOf('<section id="section-time-travel"')).toBeGreaterThan(
      source.indexOf("<StoryHeader"),
    );
    expect(source.indexOf('<section id="section-time-travel"')).toBeLessThan(
      source.indexOf("<BeliefRevisionHero"),
    );
  });

  it("keeps the analyst workspace reachable on loaded casefiles and scrolls into view on open", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain(
      "const showAnalystWorkspaceToggle = !showFirstLoadEntrypoint;",
    );
    expect(source).toContain(
      "analystWorkspaceScrollRequestedRef.current = true;",
    );
    expect(source).toContain("scrollIntoView({");
    expect(source).toContain('behavior: "smooth"');
    expect(source).toContain('block: "start"');
    expect(source).toContain("ref={analystWorkspaceSectionRef}");
  });

  it("wires the non-demo casefile header to the shared full-history rebuild flow", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain("loadCasefileSummaryCached()");
    expect(source).toContain("casefileSummary={casefileSummary}");
    expect(source).toContain("onRebuildFullHistory={handleRebuildFullHistory}");
    expect(source).toContain("fullHistoryJob={rebuildJob}");
    expect(source).toContain(
      "fullHistoryLoading={rebuildJobLoading || creatingRebuildJob}",
    );
  });

  it("keeps scripted semaglutide presentation behind explicit demo activation", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain(
      "const [demoPresentationActive, setDemoPresentationActive] = useState(false);",
    );
    expect(source).toMatch(
      /const isPrimaryDemoDrug =\s*selectedDrugId === "semaglutide" && demoPresentationActive;/,
    );
    expect(source).toContain(
      'const isSemaglutideScorecardDrug = selectedDrugId === "semaglutide";',
    );
    expect(source).toContain(
      'const scorecardPresentationMode = isSemaglutideScorecardDrug',
    );
    expect(source).toContain(
      "const scorecardPinnedToLatestForDemo = isSemaglutideScorecardDrug;",
    );
    expect(source).toContain("entries={displayedScorecard}");
    expect(source).toContain("asOfQuarter={scorecardQuarterLabel}");
    expect(source).toContain("presentationMode={scorecardPresentationMode}");
  });

  it("reattaches the casefile to the latest active rebuild job for the selected drug", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain(
      "const payload = await getActiveDrugFullHistoryRebuildJob(",
    );
    expect(source).toContain("controller.signal");
    expect(source).toContain("persistRebuildJobId(selectedDrugId, payload.id)");
  });

  it("deduplicates time-travel summary and belief diff fetches through shared caches", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain("const clearTimeTravelCaches = useCallback(() => {");
    expect(source).toContain("const loadBeliefDiffCached = useCallback(");
    expect(source).toContain("const loadCasefileSummaryCached = useCallback(");
    expect(source).toContain("buildBeliefDiffCacheKey(pair.beforeId, pair.afterId)");
    expect(source).toContain("loadCasefileSummaryCached(activeQuarter)");
  });

  it("lets the semaglutide receipt metric time-travel without unpinning the demo scorecard", () => {
    const source = readFileSync(resolve(thisDir, "Dashboard.tsx"), "utf8");
    expect(source).toContain("const metricsScorecardProjectionQuarter =");
    expect(source).toContain("const metricsScorecardAsOfViewed = useMemo(");
    expect(source).toContain("const visibleMetricsScorecardAsOfViewed = useMemo(");
    expect(source).toContain("const scorecardPinnedToLatestForDemo = isSemaglutideScorecardDrug;");
    expect(source).toContain("visibleMetricsScorecardAsOfViewed");
  });
});
