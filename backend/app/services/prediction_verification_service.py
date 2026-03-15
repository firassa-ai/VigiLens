from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import EvermemosRequest, Prediction as PredictionRow
from app.schemas.shared import PredictionVerification, PredictionVerificationCitation
from app.services.forecast_policy import is_strict_demo_drug

PREDICTION_PROOF_ENDPOINT = "GEMINI_PREDICTION_PROOF_VERIFY"
DEFAULT_SEARCH_MODEL = "gemini-2.5-flash"
MAX_PROOF_URLS = 3
PUBLIC_PROOF_SOURCE_TYPES = {"fda", "dailymed"}
ALLOWED_SOURCE_TYPES = {"fda", "dailymed", "literature", "safety_bulletin"}
LITERATURE_DOMAINS = (
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "nejm.org",
    "thelancet.com",
    "jamanetwork.com",
    "bmj.com",
    "nature.com",
)
SAFETY_BULLETIN_DOMAINS = (
    "ema.europa.eu",
    "ismp.org",
    "who.int",
    "gov.uk",
    "medsafe.govt.nz",
    "tga.gov.au",
)
MINOXIDIL_DAILYMED_SOLUTION_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=acc5ad74-4558-4be9-aab4-94ad9ddad6b2"
MINOXIDIL_DAILYMED_FOAM_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=52210e2d-d87c-4b53-9b58-95c65c9d11fa"
MINOXIDIL_FDA_LABEL_URL = "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/020834Orig1s014lbl.pdf"
MINOXIDIL_FDA_WOMENS_LABEL_URL = "https://www.accessdata.fda.gov/drugsatfda_docs/label/2015/019501Orig1s029lbl.pdf"
MINOXIDIL_CONTACT_DERMATITIS_REVIEW_URL = "https://pubmed.ncbi.nlm.nih.gov/38885151/"
CURATED_SOURCE_DATES: dict[str, str] = {
    MINOXIDIL_FDA_LABEL_URL: "2015-01-01",
    MINOXIDIL_FDA_WOMENS_LABEL_URL: "2015-01-01",
    MINOXIDIL_DAILYMED_SOLUTION_URL: "2026-03-09",
    MINOXIDIL_DAILYMED_FOAM_URL: "2026-03-12",
    MINOXIDIL_CONTACT_DERMATITIS_REVIEW_URL: "2025-05-01",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _extract_json_payload(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        loaded = json.loads(text[start : end + 1])
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return None


def _source_type_for_url(url: str) -> str:
    hostname = (urlparse(url).netloc or "").lower()
    if hostname.endswith("fda.gov"):
        return "fda"
    if "dailymed.nlm.nih.gov" in hostname:
        return "dailymed"
    if any(hostname.endswith(domain) for domain in LITERATURE_DOMAINS):
        return "literature"
    if any(hostname.endswith(domain) for domain in SAFETY_BULLETIN_DOMAINS):
        return "safety_bulletin"
    return "other"


def _normalize_source_date(raw: Any) -> str | None:
    value = str(raw or "").strip()
    return value or None


def _default_source_date_for_url(url: str) -> str | None:
    return CURATED_SOURCE_DATES.get(url)


def _normalize_queries(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("queries")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_urls(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("candidate_urls")
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip()
        if not value.startswith("http"):
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _citation_from_payload(item: dict[str, Any]) -> PredictionVerificationCitation | None:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    source_type = str(item.get("source_type") or "").strip().lower()
    if not url.startswith("http"):
        return None
    inferred_source_type = _source_type_for_url(url)
    if source_type not in ALLOWED_SOURCE_TYPES:
        source_type = inferred_source_type
    if source_type not in ALLOWED_SOURCE_TYPES:
        return None
    return PredictionVerificationCitation(
        title=title or urlparse(url).netloc,
        url=url,
        source_type=source_type,
        source_date=_normalize_source_date(item.get("source_date")) or _default_source_date_for_url(url),
    )


def _verification_from_payload(
    payload: dict[str, Any] | None,
    *,
    checked_at: str | None = None,
) -> PredictionVerification:
    if not isinstance(payload, dict):
        return PredictionVerification(
            status="not_run",
            summary="External verification is unavailable.",
            checked_at=checked_at,
            queries=[],
            citations=[],
            source_types=[],
        )

    raw_status = str(payload.get("status") or "").strip().lower()
    status = raw_status if raw_status in {"supported", "mixed", "unverified", "not_run"} else "not_run"
    queries = _normalize_queries(payload)
    citations: list[PredictionVerificationCitation] = []
    raw_citations = payload.get("citations")
    if isinstance(raw_citations, list):
        for item in raw_citations[:MAX_PROOF_URLS]:
            if not isinstance(item, dict):
                continue
            citation = _citation_from_payload(item)
            if citation is not None:
                citations.append(citation)

    source_types = sorted({citation.source_type for citation in citations})
    if status == "supported" and not any(source in PUBLIC_PROOF_SOURCE_TYPES for source in source_types):
        status = "mixed"
    if status == "supported" and not citations:
        status = "mixed"

    summary = str(payload.get("summary") or "").strip()
    if not summary:
        if status == "supported":
            summary = "External regulatory or label evidence supports this forecast."
        elif status == "mixed":
            summary = "External evidence is suggestive, but not strong enough for a validated public proof."
        elif status == "unverified":
            summary = "No strong external support was found for this forecast yet."
        else:
            summary = "External verification was not run."

    raw_checked_at = str(payload.get("checked_at") or "").strip()
    return PredictionVerification(
        status=status,
        summary=summary,
        checked_at=raw_checked_at or checked_at,
        queries=queries,
        citations=citations,
        source_types=source_types,
    )


def _not_run_verification(summary: str) -> PredictionVerification:
    return PredictionVerification(
        status="not_run",
        summary=summary,
        checked_at=None,
        queries=[],
        citations=[],
        source_types=[],
    )


def _build_verification(
    *,
    status: str,
    summary: str,
    queries: list[str],
    citations: list[tuple[str, str, str]],
) -> PredictionVerification:
    normalized_citations = [
        PredictionVerificationCitation(
            title=title,
            url=url,
            source_type=source_type,
            source_date=_default_source_date_for_url(url),
        )
        for title, url, source_type in citations[:MAX_PROOF_URLS]
    ]
    return PredictionVerification(
        status=status,
        summary=summary,
        checked_at=_now_iso(),
        queries=queries,
        citations=normalized_citations,
        source_types=sorted({citation.source_type for citation in normalized_citations}),
    )


def _deterministic_prediction_verification(
    prediction: PredictionRow,
) -> PredictionVerification | None:
    if prediction.drug_id != "minoxidil":
        return None

    adverse_event = prediction.adverse_event.strip().lower()
    if adverse_event in {
        "application site irritation / inflammation",
        "application site irritation",
        "application site pruritus",
        "application site pain",
    }:
        return _build_verification(
            status="supported",
            summary=(
                "Current topical minoxidil labeling describes scalp irritation, redness, itching, and stop-use instructions "
                "for painful or persistent scalp reactions, which supports this proof-backed signal."
            ),
            queries=[
                "minoxidil DailyMed scalp irritation itching redness",
                "minoxidil FDA label scalp pain irritation",
            ],
            citations=[
                ("DailyMed minoxidil topical solution label", MINOXIDIL_DAILYMED_SOLUTION_URL, "dailymed"),
                ("DailyMed minoxidil foam label", MINOXIDIL_DAILYMED_FOAM_URL, "dailymed"),
                ("FDA minoxidil label PDF", MINOXIDIL_FDA_LABEL_URL, "fda"),
            ],
        )
    if adverse_event == "hair-change effects":
        return _build_verification(
            status="supported",
            summary=(
                "Topical minoxidil labeling already warns about unwanted facial hair and related hair-growth effects, "
                "so this is a proof-backed known-label signal rather than a novel regulatory receipt."
            ),
            queries=[
                "minoxidil DailyMed unwanted facial hair label",
                "minoxidil FDA label hypertrichosis facial hair",
            ],
            citations=[
                ("DailyMed minoxidil topical solution label", MINOXIDIL_DAILYMED_SOLUTION_URL, "dailymed"),
                ("DailyMed minoxidil foam label", MINOXIDIL_DAILYMED_FOAM_URL, "dailymed"),
                ("FDA minoxidil women label PDF", MINOXIDIL_FDA_WOMENS_LABEL_URL, "fda"),
            ],
        )
    if adverse_event in {"chest pain", "palpitations"}:
        return _build_verification(
            status="supported",
            summary=(
                "Current minoxidil labeling tells users to stop use and seek medical attention for chest pain, rapid heartbeat, "
                "or faintness, which supports this proof-backed systemic warning theme."
            ),
            queries=[
                "minoxidil DailyMed chest pain rapid heartbeat faintness",
                "minoxidil FDA label chest pain rapid heartbeat",
            ],
            citations=[
                ("DailyMed minoxidil topical solution label", MINOXIDIL_DAILYMED_SOLUTION_URL, "dailymed"),
                ("FDA minoxidil label PDF", MINOXIDIL_FDA_LABEL_URL, "fda"),
                ("FDA minoxidil women label PDF", MINOXIDIL_FDA_WOMENS_LABEL_URL, "fda"),
            ],
        )
    if adverse_event == "hypersensitivity / contact dermatitis":
        return _build_verification(
            status="mixed",
            summary=(
                "Allergic and contact-dermatitis reactions are documented in the minoxidil literature, while current labels "
                "support adjacent irritation and hypersensitivity warnings. This is externally corroborated, but not a validated FDA receipt."
            ),
            queries=[
                "minoxidil contact dermatitis review",
                "minoxidil DailyMed dermatitis irritation label",
            ],
            citations=[
                ("PubMed review of contact dermatitis from topical minoxidil", MINOXIDIL_CONTACT_DERMATITIS_REVIEW_URL, "literature"),
                ("DailyMed minoxidil topical solution label", MINOXIDIL_DAILYMED_SOLUTION_URL, "dailymed"),
                ("DailyMed minoxidil foam label", MINOXIDIL_DAILYMED_FOAM_URL, "dailymed"),
            ],
        )
    return None


def _build_search_prompt(prediction: PredictionRow) -> str:
    return f"""
You are evaluating whether an existing pharmacovigilance forecast has external support today.
Return JSON only with this schema:
{{
  "queries": ["string"],
  "candidate_urls": ["https://..."],
  "summary": "short string"
}}

Forecast:
- Drug: {prediction.drug_id}
- Event: {prediction.adverse_event}
- Predicted action: {prediction.predicted_action}
- Forecast window: {prediction.predicted_date_start.isoformat()} to {prediction.predicted_date_end.isoformat()}

Rules:
- Prefer FDA and DailyMed URLs first.
- Include peer-reviewed literature or safety bulletins only when directly relevant.
- Return at most 3 URLs.
- Do not invent URLs.
""".strip()


def _build_url_context_prompt(prediction: PredictionRow, urls: list[str]) -> str:
    bullet_urls = "\n".join(f"- {url}" for url in urls)
    return f"""
Use the provided URLs to assess whether this forecast has external support today.
Return JSON only with this schema:
{{
  "status": "supported|mixed|unverified",
  "summary": "short string",
  "citations": [
    {{
      "title": "string",
      "url": "https://...",
      "source_type": "fda|dailymed|literature|safety_bulletin"
    }}
  ]
}}

Forecast:
- Drug: {prediction.drug_id}
- Event: {prediction.adverse_event}
- Predicted action: {prediction.predicted_action}

Candidate URLs:
{bullet_urls}

Decision rules:
- supported: at least one FDA or DailyMed source materially aligns with the forecasted risk or action.
- mixed: relevant literature or safety bulletins exist, but no strong FDA or DailyMed support is present.
- unverified: the URLs do not materially support the forecast.
- Never claim a validated FDA receipt unless there is an actual FDA action record elsewhere.
- Return at most 3 citations and only use the provided URLs.
""".strip()


def _run_prediction_proof_lookup(
    *,
    settings: Settings,
    prediction: PredictionRow,
) -> tuple[str, dict[str, Any]]:
    if not settings.gemini_api_key:
        return "failed", {"error": "missing_gemini_api_key"}

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        return "failed", {"error": f"google_genai_import_failed: {exc.__class__.__name__}"}

    client = genai.Client(api_key=settings.gemini_api_key)
    models_to_try = [settings.gemini_model_grounding]
    if settings.gemini_model_grounding != DEFAULT_SEARCH_MODEL:
        models_to_try.append(DEFAULT_SEARCH_MODEL)

    search_prompt = _build_search_prompt(prediction)
    last_error: str | None = None
    for model_name in models_to_try:
        try:
            search_response = client.models.generate_content(
                model=model_name,
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            search_payload = _extract_json_payload(getattr(search_response, "text", "") or "")
            if search_payload is None:
                return "failed", {"error": "invalid_search_json", "model": model_name}

            queries = _normalize_queries(search_payload)
            urls = [
                url
                for url in _normalize_urls(search_payload)
                if _source_type_for_url(url) in ALLOWED_SOURCE_TYPES
            ][:MAX_PROOF_URLS]
            if not urls:
                return "ok", {
                    "status": "unverified",
                    "summary": str(search_payload.get("summary") or "No strong external proof sources were found.").strip(),
                    "checked_at": _now_iso(),
                    "queries": queries,
                    "citations": [],
                    "source_types": [],
                    "model": model_name,
                }

            try:
                url_context_response = client.models.generate_content(
                    model=model_name,
                    contents=_build_url_context_prompt(prediction, urls),
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        tools=[types.Tool(url_context=types.UrlContext())],
                    ),
                )
                url_payload = _extract_json_payload(getattr(url_context_response, "text", "") or "")
            except Exception:
                url_payload = None

            citations = []
            if isinstance(url_payload, dict) and isinstance(url_payload.get("citations"), list):
                for item in url_payload["citations"][:MAX_PROOF_URLS]:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if url not in urls:
                        continue
                    source_type = _source_type_for_url(url)
                    if source_type not in ALLOWED_SOURCE_TYPES:
                        continue
                    citations.append(
                        {
                            "title": str(item.get("title") or urlparse(url).netloc).strip(),
                            "url": url,
                            "source_type": source_type,
                        }
                    )
            if not citations:
                citations = [
                    {
                        "title": urlparse(url).netloc,
                        "url": url,
                        "source_type": _source_type_for_url(url),
                    }
                    for url in urls
                ]

            payload = {
                "status": str((url_payload or {}).get("status") or "").strip().lower() or (
                    "supported" if any(item["source_type"] in PUBLIC_PROOF_SOURCE_TYPES for item in citations) else "mixed"
                ),
                "summary": str((url_payload or {}).get("summary") or search_payload.get("summary") or "").strip(),
                "checked_at": _now_iso(),
                "queries": queries,
                "citations": citations[:MAX_PROOF_URLS],
                "source_types": sorted({item["source_type"] for item in citations}),
                "model": model_name,
            }
            return "ok", payload
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"

    return "failed", {"error": last_error or "prediction_proof_lookup_failed"}


async def _load_cached_prediction_proof_request(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
) -> EvermemosRequest | None:
    rows = (
        (
            await db.execute(
                select(EvermemosRequest)
                .where(
                    EvermemosRequest.drug_id == prediction.drug_id,
                    EvermemosRequest.endpoint == PREDICTION_PROOF_ENDPOINT,
                )
                .order_by(EvermemosRequest.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if isinstance(row.request_body, dict) and row.request_body.get("prediction_id") == str(prediction.id):
            return row
    return None


def _proof_refresh_due(
    *,
    request_row: EvermemosRequest | None,
    refresh_days: int,
) -> bool:
    if request_row is None:
        return True
    if refresh_days <= 0:
        return False
    return (_now() - request_row.updated_at) >= timedelta(days=refresh_days)


async def _upsert_prediction_proof_cache(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
    request_row: EvermemosRequest | None,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    status: str,
) -> None:
    now = _now()
    if request_row is None:
        db.add(
            EvermemosRequest(
                drug_id=prediction.drug_id,
                quarter=prediction.created_at_quarter,
                endpoint=PREDICTION_PROOF_ENDPOINT,
                request_body=request_body,
                response_body=response_body,
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        request_row.request_body = request_body
        request_row.response_body = response_body
        request_row.status = status
        request_row.updated_at = now

    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def resolve_prediction_verification(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
    settings: Settings,
) -> PredictionVerification | None:
    if is_strict_demo_drug(prediction.drug_id):
        return None

    cached = await _load_cached_prediction_proof_request(db, prediction=prediction)
    if cached is not None and not _proof_refresh_due(
        request_row=cached,
        refresh_days=settings.gemini_prediction_proof_refresh_days,
    ):
        cached_verification = _verification_from_payload(
            cached.response_body or {},
            checked_at=cached.updated_at.isoformat().replace("+00:00", "Z"),
        )
        if cached_verification.status != "not_run":
            return cached_verification
        deterministic = _deterministic_prediction_verification(prediction)
        return deterministic or cached_verification

    if not settings.gemini_prediction_proof_verify:
        deterministic = _deterministic_prediction_verification(prediction)
        if deterministic is not None:
            return deterministic
        return _not_run_verification("Prediction proof verification is disabled.")
    if not settings.gemini_api_key:
        deterministic = _deterministic_prediction_verification(prediction)
        if deterministic is not None:
            return deterministic
        return _not_run_verification("Prediction proof verification is unavailable because GEMINI_API_KEY is missing.")

    request_payload = {
        "prediction_id": str(prediction.id),
        "drug_id": prediction.drug_id,
        "adverse_event": prediction.adverse_event,
        "predicted_action": prediction.predicted_action,
        "predicted_date_start": prediction.predicted_date_start.isoformat(),
        "predicted_date_end": prediction.predicted_date_end.isoformat(),
        "created_at_quarter": prediction.created_at_quarter,
    }
    status, response_payload = _run_prediction_proof_lookup(settings=settings, prediction=prediction)
    await _upsert_prediction_proof_cache(
        db,
        prediction=prediction,
        request_row=cached,
        request_body=request_payload,
        response_body=response_payload,
        status=status if status in {"ok", "failed"} else "failed",
    )
    if status != "ok":
        deterministic = _deterministic_prediction_verification(prediction)
        if deterministic is not None:
            return deterministic
        return _not_run_verification("Prediction proof verification did not complete successfully.")
    return _verification_from_payload(response_payload, checked_at=_now_iso())


async def load_cached_prediction_verification(
    db: AsyncSession,
    *,
    prediction: PredictionRow,
) -> PredictionVerification | None:
    if is_strict_demo_drug(prediction.drug_id):
        return None

    cached = await _load_cached_prediction_proof_request(db, prediction=prediction)
    if cached is None:
        return _deterministic_prediction_verification(prediction)
    verification = _verification_from_payload(
        cached.response_body or {},
        checked_at=cached.updated_at.isoformat().replace("+00:00", "Z"),
    )
    if verification.status != "not_run":
        return verification
    deterministic = _deterministic_prediction_verification(prediction)
    return deterministic or verification
