# VigiLens

VigiLens is an open-source pharmacovigilance platform for turning post-market adverse-event data into auditable drug-safety casefiles.

It combines standard signal-detection science with longitudinal memory so teams can move from raw FAERS volume to an interpretable safety narrative: what is happening, how it evolved over time, what evidence supports it, and which regulatory actions may follow.

## What The Product Does

VigiLens is built for post-market drug surveillance workflows:

- search and preview candidate drugs before tracking them
- ingest FDA adverse-event data quarter by quarter
- compute disproportionality-based safety signals across time
- organize evidence into casefiles, timelines, profiles, and signal families
- distinguish known labeled effects from potential label-gap signals
- store longitudinal context in memory so the system can reason over change, not just snapshots
- generate and track regulatory forecasts with explicit provenance
- answer natural-language safety questions grounded in stored evidence and memory

## Why Memory Matters

Pharmacovigilance is not just a counting problem. A single report can look like noise when it arrives and become meaningful only after years of additional evidence accumulate. VigiLens is designed around that reality.

The product treats memory as structural, not decorative:

- `EventLog` captures report-level evidence as timestamped facts
- `Episodic` memory stores quarter-aware summaries of what changed
- `Profile` memory tracks the evolving safety identity of a drug
- `Foresight` memory stores explicit predictions and later validation status

Postgres remains the canonical source of truth. EverMemOS augments temporal reasoning, provenance, recall, and forecast tracking. If the memory layer is unavailable, the core signal and casefile flow still runs.

## How VigiLens Uses EverMind.ai Memory

VigiLens uses the EverMind.ai memory layer through EverMemOS as a real product subsystem, not as a wrapper around the UI.

Each tracked drug gets its own memory namespace, so semaglutide, minoxidil, and any future tracked drug retain isolated longitudinal context rather than sharing one pooled memory stream.

During ingestion and seeded replay, VigiLens writes multiple memory shapes into EverMind.ai:

- `EventLog`: report-level evidence memories for representative FAERS cases with citations and quarter context
- `Episodic`: quarter digests that summarize what changed in signal strength, trajectory, and safety narrative
- `Profile`: evolving drug-level safety state, including active risks and current interpretation
- `Foresight`: explicit regulatory forecasts with status, confidence, and traceable context

That memory is then used at read time:

- the belief and query flows retrieve episodic context before generating safety assessments
- the analyst surfaces pull profile and episodic memory back into the casefile experience
- the forecast layer uses memory writes and validation status to show whether a prediction is stored, pending, or validated
- the evidence flow keeps report-level provenance visible instead of collapsing everything into a summary-only UI

In practical terms, EverMind.ai is what allows VigiLens to preserve the story of a drug over time: not only which signals exist now, but what the system saw earlier, what changed quarter by quarter, and which prior evidence becomes newly important in light of later data.

The memory layer is also isolated from the source of truth by design. Postgres remains canonical for reports, stats, beliefs, predictions, and cached provenance. If EverMind.ai is unavailable, VigiLens degrades gracefully to deterministic signal, casefile, and fallback reasoning paths instead of breaking the product.

## Scientific Methodology

VigiLens uses established pharmacovigilance methods rather than invented scoring.

### Data foundations

- `FAERS / openFDA`: source for adverse-event reports, reactions, drugs, outcomes, and quarterly accumulation
- `DailyMed`: source for current label coverage so the system can separate known effects from candidate label gaps
- `FDA actions`: source for validating or contextualizing forecasted safety communications, warnings, and label changes

### Signal detection

The signal engine computes cumulative and quarter-aware statistics for drug-event pairs using standard disproportionality analysis:

- `ROR` (Reporting Odds Ratio)
- `PRR` (Proportional Reporting Ratio)
- `chi-square`
- `BCPNN`
- `EBGM`

Those metrics are interpreted with supporting counts, confidence bounds, label status, and trajectory classification. Signals are then grouped into casefile-friendly families and ranked by consensus and priority.

### Longitudinal reasoning

VigiLens does not stop at a point-in-time signal table. It keeps quarterly state so it can describe whether a signal is:

- `emerging`
- `accelerating`
- `stable`
- `declining`
- `insufficient_data`

That temporal layer matters because pharmacovigilance decisions depend on whether a pattern is new, persistent, intensifying, or already understood.

### Evidence and forecasts

The product builds auditable outputs on top of the science:

- current-quarter casefile summaries
- proof-backed or receipt-style forecast tracks
- report-level evidence spotlights
- memory-backed drug profiles
- query responses grounded in signals, evidence, and recalled context

## System Architecture

```text
openFDA / repo-shipped FAERS fixtures
                |
                v
Postgres (canonical reports, stats, beliefs, predictions, cached provenance)
                |
                +--> signal engine (ROR / PRR / chi-square / BCPNN / EBGM)
                |
                +--> EverMemOS (episodic, profile, event-log, foresight augmentation)
                |
                +--> Gemini reasoning + proof verification via Google GenAI SDK
                |
                v
Discover surface + casefile surface + analyst workspace
```

- Postgres stores reports, quarterly stats, beliefs, predictions, and cached provenance payloads.
- EverMemOS augments episodic recall, evolving profile context, event-log provenance, and foresight memory.
- Gemini is optional. If `GEMINI_API_KEY` is missing, the platform falls back to deterministic reasoning paths for demo and local verification flows.
- Shared Pydantic and TypeScript contracts define the API boundary.

## Product Surfaces

- `Discover`: search the drug catalog, inspect label and FAERS coverage, and start tracking jobs
- `Casefile`: review current-quarter narrative, lead signals, label-gap cues, and forecast status
- `Analyst workspace`: inspect signal trajectories, evidence spotlight, memory timeline, profile, and thought stream
- `API`: integrate catalog, ingest, casefile, query, and progress surfaces into external workflows

## Shipped Sample Data

The repository includes public fixtures so a fresh clone is testable immediately:

- `semaglutide`: `2,237` suspect reports through `2023-Q4` in `data/real/semaglutide.ndjson`
- `minoxidil`: `28,236` suspect reports through `2023-Q4` in `data/real/minoxidil.ndjson`
- `metformin`: `1,023` suspect reports in `data/real/metformin.ndjson`

By default, local bootstrap seeds a two-drug portfolio:

- semaglutide as the earlier baseline path
- full-history minoxidil as the larger current-state casefile

A lightweight fallback fixture for minoxidil is also available in `data/demo/minoxidil.ndjson` for narrower local experiments.

## Run Locally

1. Copy `.env.example` to `.env.local`.
2. Optionally set `GEMINI_API_KEY` for live reasoning and proof refresh, `OPENFDA_API_KEY` for deeper live pulls, and `OPENAI_API_KEY` or `DEEPINFRA_API_KEY` for EverMemOS model access.
3. Start the default local stack:

```bash
./scripts/run-dev.sh --force-seed
```

This boot path:

- starts local Postgres automatically
- starts the backend and frontend
- auto-seeds the shipped semaglutide and minoxidil portfolio
- auto-clones EverMemOS on first run when the memory stack is enabled

If you want the deterministic fallback path without EverMemOS:

```bash
./scripts/run-dev.sh --force-seed --no-evermemos
```

On a fresh boot, the full-history minoxidil seed can take around two minutes. When the backend becomes healthy and seeding completes, open:

- Product UI: `http://localhost:3000/discover`
- Backend health: `http://localhost:8000/api/v1/health`

The seeded portfolio remains usable from the checked-in fixtures even if Gemini or EverMemOS are unavailable.

## How To Use It

### Explore the shipped portfolio

Start on `Discover` and open either seeded example drug:

- use `semaglutide` to inspect the baseline-to-receipt path
- use `minoxidil` to inspect the larger full-history proof-backed casefile

### Inspect a casefile

Inside a tracked drug view, VigiLens is designed to answer four practical questions:

- what are the lead signals right now
- which ones look known versus potentially novel
- how did the pattern evolve quarter by quarter
- what evidence and memory support that interpretation

### Ask safety questions

Use the analyst workspace or `POST /api/v1/query` to ask for grounded safety summaries, trend interpretation, or evidence-backed explanations tied to a tracked drug.

### Track another drug

Use the catalog preview flow to inspect availability, then create a tracking job. The backend supports async tracking jobs and ingest progress over WebSocket.

## Key API Surfaces

- `GET /api/v1/catalog/search`
- `GET /api/v1/catalog/preview`
- `POST /api/v1/tracking/jobs`
- `GET /api/v1/tracking/jobs/{job_id}`
- `GET /api/v1/drugs`
- `GET /api/v1/drugs/{drug_id}/casefile-summary`
- `GET /api/v1/drugs/{drug_id}/scorecard`
- `GET /api/v1/drugs/{drug_id}/profile`
- `GET /api/v1/drugs/{drug_id}/timeline`
- `POST /api/v1/query`
- `GET /api/v1/ingest/status`
- `WS /ws/ingest-progress`

## Product Demo

[![Watch the product demo on YouTube](https://img.youtube.com/vi/mEkoP3VevdA/maxresdefault.jpg)](https://youtu.be/mEkoP3VevdA)

## Open Source License

VigiLens is licensed under `GNU AGPL-3.0-only`.

That means:

- research, internal evaluation, and open collaboration are allowed under a standard OSI-approved copyleft license
- if you distribute modified versions, or run a modified network service for users, you must provide the corresponding source under the same license
- if your organization wants to use VigiLens without AGPL reciprocity obligations, you should contact the maintainers for separate commercial terms

This is the strongest mainstream open-source option for protecting a networked product while keeping the community version open.

## Safety and Scope

- VigiLens is a pharmacovigilance intelligence and surveillance tool, not medical advice.
- FAERS is a spontaneous-reporting system with under-reporting, duplication risk, and no causal proof on its own.
- The platform is designed to surface signals, evidence chains, and forecasts for analyst review, not to make clinical determinations.
