from app.engine.category_baseline.schema import Tier


def classify_tier(months_observed: int, opted_out: bool = False) -> Tier:
    if opted_out or months_observed < 3:
        return Tier.T1
    if months_observed <= 4:
        return Tier.T2
    if months_observed <= 11:
        return Tier.T3
    return Tier.T4
