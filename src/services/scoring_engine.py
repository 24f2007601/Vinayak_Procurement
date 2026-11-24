"""Deterministic Vendor Scoring & Comparative Statement Engine.

Calculates multi-factor rankings:
- 60% Landed Cost (relative to L1)
- 25% On-Time Delivery Track Record
- 15% Quality Pass Track Record
Minus dispute penalties.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict
from src.constants import (
    WEIGHT_PRICE,
    WEIGHT_DELIVERY,
    WEIGHT_QUALITY,
    DISPUTE_PENALTY_PER_INCIDENT,
    MAX_DISPUTE_PENALTY,
)
from src.models.quote import NormalizedQuoteItem
from src.models.comparative import (
    VendorTrackRecord,
    RankedVendor,
    ComparativeStatement,
    ApprovalStatus,
)
from src.services.cost_engine import round_currency

FOUR_DECIMALS = Decimal("0.0001")


def round_score(score: Decimal) -> Decimal:
    """Rounds score to 4 decimal places."""
    return score.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)


def calculate_price_score(vendor_landed_cost: Decimal, l1_landed_cost: Decimal) -> Decimal:
    """Calculates relative price score against L1."""
    if vendor_landed_cost <= 0:
        return Decimal("0.0")
    # L1 gets 1.0; higher cost gets proportionally lower score
    score = l1_landed_cost / vendor_landed_cost
    return round_score(min(score, Decimal("1.0")))


def calculate_composite_score(
    price_score: Decimal,
    track_record: VendorTrackRecord
) -> Decimal:
    """Calculates weighted composite score with penalties."""
    norm_delivery = track_record.on_time_delivery_pct / Decimal("100.0")
    norm_quality = track_record.quality_pass_pct / Decimal("100.0")

    base_score = (
        (price_score * WEIGHT_PRICE) +
        (norm_delivery * WEIGHT_DELIVERY) +
        (norm_quality * WEIGHT_QUALITY)
    )

    # Deduct dispute penalties
    dispute_deduction = min(
        Decimal(track_record.active_disputes) * DISPUTE_PENALTY_PER_INCIDENT,
        MAX_DISPUTE_PENALTY
    )

    final_score = max(base_score - dispute_deduction, Decimal("0.0"))
    return round_score(final_score)


def compose_decision_rationale(
    vendor: NormalizedQuoteItem,
    is_l1: bool,
    is_recommended: bool,
    track: VendorTrackRecord,
    l1_vendor_name: str
) -> str:
    """Generates concise, audit-defensible reasoning in plain English."""
    reasons = []

    if is_l1 and is_recommended:
        reasons.append("Lowest landed cost with clean execution track record.")
    elif is_l1 and not is_recommended:
        reasons.append(
            f"Lowest commercial bidder, but not recommended due to {track.active_disputes} active dispute(s) "
            f"and lower on-time delivery rate ({track.on_time_delivery_pct}%)."
        )
    elif is_recommended:
        reasons.append(
            f"Recommended over L1 ({l1_vendor_name}) due to superior reliability ({track.on_time_delivery_pct}% on-time, "
            f"{track.quality_pass_pct}% quality pass rate) and zero active dispute risks."
        )
    else:
        reasons.append("Higher landed cost compared to recommended option.")

    if vendor.exclusions:
        reasons.append(f"Exclusions noted: {', '.join(vendor.exclusions)}.")

    return " ".join(reasons)


def generate_comparative_statement(
    statement_id: str,
    project_name: str,
    package_title: str,
    boq_quantity: Decimal,
    budget_rate: Decimal,
    quotes: List[NormalizedQuoteItem],
    track_records: Dict[str, VendorTrackRecord]
) -> ComparativeStatement:
    """Compiles normalized quotes and past records into an executive statement."""
    if not quotes:
        raise ValueError("Cannot generate comparative statement without vendor quotes")

    total_budget = round_currency(boq_quantity * budget_rate)

    # Sort strictly by total landed cost to determine true L1
    sorted_by_price = sorted(quotes, key=lambda q: q.total_landed_cost)
    l1_quote = sorted_by_price[0]
    l1_landed_cost = l1_quote.total_landed_cost
    l1_vendor_name = l1_quote.vendor_name

    evaluated_vendors: List[RankedVendor] = []

    for quote in quotes:
        track = track_records.get(
            quote.vendor_name,
            VendorTrackRecord(
                vendor_name=quote.vendor_name,
                on_time_delivery_pct=Decimal("80.0"),
                quality_pass_pct=Decimal("80.0"),
                active_disputes=0
            )
        )
        p_score = calculate_price_score(quote.total_landed_cost, l1_landed_cost)
        c_score = calculate_composite_score(p_score, track)

        evaluated_vendors.append(
            RankedVendor(
                rank=0,  # Will assign after composite sort
                vendor_name=quote.vendor_name,
                normalized_quote=quote,
                price_score=p_score,
                track_record=track,
                composite_score=c_score,
                is_l1=(quote.vendor_name == l1_vendor_name),
                is_recommended=False,
                decision_rationale=""
            )
        )

    # Rank by composite score descending
    ranked_by_composite = sorted(evaluated_vendors, key=lambda v: v.composite_score, reverse=True)
    recommended_vendor_name = ranked_by_composite[0].vendor_name

    for idx, v in enumerate(ranked_by_composite, start=1):
        v.rank = idx
        v.is_recommended = (v.vendor_name == recommended_vendor_name)
        v.decision_rationale = compose_decision_rationale(
            vendor=v.normalized_quote,
            is_l1=v.is_l1,
            is_recommended=v.is_recommended,
            track=v.track_record,
            l1_vendor_name=l1_vendor_name
        )

    exec_summary = (
        f"Evaluated {len(quotes)} quotes for {package_title} at {project_name}. "
        f"L1 bidder is {l1_vendor_name} (Landed: ₹{l1_landed_cost:,.2f}). "
        f"Recommended award: {recommended_vendor_name} (Composite Score: {ranked_by_composite[0].composite_score})."
    )

    return ComparativeStatement(
        statement_id=statement_id,
        project_name=project_name,
        package_title=package_title,
        boq_quantity=boq_quantity,
        budget_rate=budget_rate,
        total_budget=total_budget,
        ranked_vendors=ranked_by_composite,
        l1_vendor_name=l1_vendor_name,
        recommended_vendor_name=recommended_vendor_name,
        executive_summary=exec_summary,
        status=ApprovalStatus.PENDING_APPROVAL
    )
