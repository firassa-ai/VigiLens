from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

ForecastMode = Literal["strict_demo", "broad_generic"]
ForecastTrack = Literal["receipt", "proof"]
ForecastNoveltyStatus = Literal["known_label", "label_gap", "indication_confounded", "generic_noise"]

STRICT_DEMO_DRUGS = {"semaglutide"}
GENERIC_NOISE_TERMS = {
    "adverse drug reaction",
}
INDICATION_CONFOUNDED_TERMS_BY_DRUG: dict[str, set[str]] = {
    "minoxidil": {
        "alopecia",
        "alopecia areata",
        "androgenetic alopecia",
        "hair loss",
        "lichen planopilaris",
        "treatment failure",
    },
}


@dataclass(frozen=True)
class ForecastClassification:
    track: ForecastTrack
    novelty_status: ForecastNoveltyStatus
    suppress_public: bool = False


EVENT_CLASSIFICATION_OVERRIDES_BY_DRUG: dict[str, dict[str, ForecastClassification]] = {
    "minoxidil": {
        "application site irritation / inflammation": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "application site irritation": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "application site pruritus": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "application site pain": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "hair-change effects": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "chest pain": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "palpitations": ForecastClassification(
            track="proof",
            novelty_status="known_label",
        ),
        "hypersensitivity / contact dermatitis": ForecastClassification(
            track="proof",
            novelty_status="label_gap",
        ),
        "application site dryness": ForecastClassification(
            track="proof",
            novelty_status="label_gap",
            suppress_public=True,
        ),
        "headache": ForecastClassification(
            track="proof",
            novelty_status="generic_noise",
            suppress_public=True,
        ),
    }
}


def forecast_mode_for_drug(drug_id: str) -> ForecastMode:
    return "strict_demo" if drug_id in STRICT_DEMO_DRUGS else "broad_generic"


def is_strict_demo_drug(drug_id: str) -> bool:
    return forecast_mode_for_drug(drug_id) == "strict_demo"


def method_vote_count(method_votes: dict[str, bool] | None) -> int:
    return sum(1 for value in (method_votes or {}).values() if value)


def _normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def classify_generic_forecast(
    *,
    drug_id: str,
    adverse_event: str,
    label_status: str,
) -> ForecastClassification:
    normalized = _normalize_term(adverse_event)
    override = EVENT_CLASSIFICATION_OVERRIDES_BY_DRUG.get(drug_id, {}).get(normalized)
    if override is not None:
        return override
    if normalized in GENERIC_NOISE_TERMS:
        return ForecastClassification(
            track="proof",
            novelty_status="generic_noise",
            suppress_public=True,
        )
    if normalized in INDICATION_CONFOUNDED_TERMS_BY_DRUG.get(drug_id, set()):
        return ForecastClassification(
            track="proof",
            novelty_status="indication_confounded",
            suppress_public=True,
        )
    if label_status == "known_label":
        return ForecastClassification(
            track="proof",
            novelty_status="known_label",
        )
    return ForecastClassification(
        track="receipt",
        novelty_status="label_gap",
    )
