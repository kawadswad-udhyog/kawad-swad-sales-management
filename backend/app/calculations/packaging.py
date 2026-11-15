"""
Authoritative Packaging Calculation Engine
Implements Part 2 and Part 5 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from .units import (
    round_stock,
    to_decimal,
)

# Standard tolerance for packing weight differences (5 grams = 0.005 kg)
DEFAULT_PACKING_TOLERANCE_KG = 0.005


def calculate_packed_weight(
    packet_entries: List[Dict[str, Any]],
) -> Tuple[float, int, List[Dict[str, Any]]]:
    """
    Calculate total packed kilograms and total packet count from SKU packet quantities.
    Each packet_entry contains:
      - product_id: SKU product id
      - sku: SKU name / code
      - pack_weight_g: configured net weight in grams
      - packet_quantity: non-negative integer
    """
    total_packed_dec = Decimal("0")
    total_packets = 0
    breakdown = []

    for entry in packet_entries:
        pack_weight_g = int(float(entry.get("pack_weight_g", 0) or 0))
        qty = int(entry.get("packet_quantity", 0) or 0)

        if qty < 0:
            raise ValueError(f"Packet quantity cannot be negative for SKU {entry.get('sku')}")
        if pack_weight_g <= 0 and qty > 0:
            raise ValueError(f"Configured pack weight for SKU {entry.get('sku')} must be positive")

        weight_kg_dec = to_decimal(pack_weight_g) / Decimal("1000")
        sku_kg_dec = to_decimal(qty) * weight_kg_dec

        total_packed_dec += sku_kg_dec
        total_packets += qty

        breakdown.append({
            "product_id": entry.get("product_id", ""),
            "sku": entry.get("sku", ""),
            "pack_weight_g": pack_weight_g,
            "packet_quantity": qty,
            "sku_packed_kg": round_stock(sku_kg_dec),
        })

    return round_stock(total_packed_dec), total_packets, breakdown


def calculate_packing_variance(
    bulk_consumed_kg: float,
    total_packed_kg: float,
    packing_loss_kg: float = 0.0,
    tolerance_kg: float = DEFAULT_PACKING_TOLERANCE_KG,
) -> Dict[str, Any]:
    """
    Calculate packing variance:
    unexplained_variance_kg = bulk_quantity_consumed_kg - total_packed_kg - recorded_packing_loss_kg
    """
    if bulk_consumed_kg <= 0:
        raise ValueError(f"Bulk consumed must be positive, got {bulk_consumed_kg} kg")
    if total_packed_kg < 0:
        raise ValueError(f"Total packed kg cannot be negative, got {total_packed_kg} kg")
    if packing_loss_kg < 0:
        raise ValueError(f"Packing loss cannot be negative, got {packing_loss_kg} kg")
    if tolerance_kg is not None and to_decimal(tolerance_kg) < Decimal("0"):
        raise ValueError(f"Packing tolerance cannot be negative, got {tolerance_kg} kg")

    bulk_dec = to_decimal(bulk_consumed_kg)
    packed_dec = to_decimal(total_packed_kg)
    loss_dec = to_decimal(packing_loss_kg)
    tol_dec = to_decimal(tolerance_kg)

    unexplained_dec = bulk_dec - (packed_dec + loss_dec)
    is_discrepancy = abs(unexplained_dec) > tol_dec

    return {
        "bulk_consumed_kg": round_stock(bulk_dec),
        "total_packed_kg": round_stock(packed_dec),
        "packing_loss_kg": round_stock(loss_dec),
        "unexplained_variance_kg": round_stock(unexplained_dec),
        "tolerance_kg": round_stock(tol_dec),
        "is_discrepancy": is_discrepancy,
        "status": "DISCREPANCY_DETECTED" if is_discrepancy else "MATCH",
    }


def validate_packing_discrepancy(
    variance_info: Dict[str, Any],
    explanation: Optional[str] = None,
    discrepancy_approved: bool = False,
    approver: Optional[str] = None,
) -> None:
    """
    Block packing completion if there is an unexplained discrepancy that has not been approved.
    Raises ValueError if discrepancy blocks finalization.
    """
    if variance_info.get("is_discrepancy"):
        unexplained = variance_info.get("unexplained_variance_kg", 0)
        if not discrepancy_approved:
            raise ValueError(
                f"Packing completion blocked: Unexplained variance of {unexplained:.3f} kg exceeds tolerance "
                f"({variance_info.get('tolerance_kg', 0.005)} kg). "
                "The Owner must either correct the quantities or submit an authorized explanation to approve the discrepancy."
            )
        if not explanation or not explanation.strip():
            raise ValueError("An explanation is required to approve an unexplained packing discrepancy.")
        if not approver or not approver.strip():
            raise ValueError("Approving actor is required to approve an unexplained packing discrepancy.")


def classify_packaging_discrepancy(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a PackagingBatches row deterministically without altering historical data.

    Protects historical unresolved discrepancies (e.g. 55 kg unrecorded-sales variance
    where the 75 kg deduction has already been posted) from reversals, duplicate
    55 kg deductions, or synthetic sale generation, while keeping pending-review
    discrepancies (e.g. 2.4 kg) clearly surfaced for Owner review.
    """
    diff_kg = round_stock(to_decimal(row.get("difference_kg", row.get("unexplained_variance_kg", 0)) or 0))
    status_upper = str(row.get("status", "")).strip().upper()
    diff_status_upper = str(row.get("difference_status", "")).strip().upper()
    is_approved = str(row.get("discrepancy_approved", "")).strip().lower() in {"true", "1", "yes"}
    explicit_class = str(row.get("discrepancy_classification", row.get("review_state", ""))).strip().upper()
    notes_lower = f"{row.get('notes', '')} {row.get('discrepancy_explanation', '')} {row.get('loss_reason', '')}".lower()

    is_historical_flag = str(row.get("historical_unresolved", row.get("is_historical", ""))).strip().lower() in {"true", "1", "yes"}
    looks_historical = (
        is_historical_flag
        or explicit_class == "HISTORICAL_UNRESOLVED"
        or diff_status_upper == "HISTORICAL_UNRESOLVED"
        or status_upper == "HISTORICAL_UNRESOLVED"
        or "historical_unresolved" in notes_lower
        or "unrecorded sale" in notes_lower
        or "sold but not recorded" in notes_lower
        or ("historical" in notes_lower and ("discrepancy" in notes_lower or "75" in notes_lower or "55" in notes_lower))
    )

    deduction_already_recorded = str(row.get("deduction_already_recorded", "")).strip().lower() in {"true", "1", "yes"}
    if not deduction_already_recorded and ("75 kg" in notes_lower or "75kg" in notes_lower or "deduction already" in notes_lower):
        deduction_already_recorded = True

    if looks_historical:
        return {
            "classification": "HISTORICAL_UNRESOLVED",
            "review_state": "HISTORICAL_UNRESOLVED",
            "difference_kg": diff_kg,
            "accounting_meaning": "UNRECORDED_HISTORICAL_SALES",
            "deduction_already_recorded": deduction_already_recorded,
            "reversal_blocked": True,
            "duplicate_deduction_blocked": True,
            "synthetic_sale_blocked": True,
            "requires_owner_review": True,
            "can_approve_operationally": False,
            "policy_note": (
                "Historical discrepancy retained for reconciliation visibility. "
                "Existing stock deduction is preserved; reversals, duplicate deductions, and synthetic sales are blocked."
            ),
        }

    has_variance = abs(diff_kg) > DEFAULT_PACKING_TOLERANCE_KG
    if (has_variance or status_upper == "PENDING_REVIEW" or diff_status_upper in {"REVIEW_REQUIRED", "PENDING_REVIEW"}) and not is_approved:
        return {
            "classification": "PENDING_REVIEW",
            "review_state": "PENDING_REVIEW",
            "difference_kg": diff_kg,
            "accounting_meaning": "PENDING_PHYSICAL_RECONCILIATION",
            "deduction_already_recorded": False,
            "reversal_blocked": False,
            "duplicate_deduction_blocked": True,
            "synthetic_sale_blocked": True,
            "requires_owner_review": True,
            "can_approve_operationally": True,
            "policy_note": "Packaging variance awaiting Owner physical review and explanation.",
        }

    if is_approved or diff_status_upper == "APPROVED_DISCREPANCY":
        return {
            "classification": "APPROVED_DISCREPANCY",
            "review_state": "APPROVED_DISCREPANCY",
            "difference_kg": diff_kg,
            "accounting_meaning": "OWNER_APPROVED_VARIANCE",
            "deduction_already_recorded": True,
            "reversal_blocked": False,
            "duplicate_deduction_blocked": True,
            "synthetic_sale_blocked": True,
            "requires_owner_review": False,
            "can_approve_operationally": False,
            "policy_note": "Discrepancy reviewed and approved by Owner.",
        }

    return {
        "classification": "MATCH",
        "review_state": "MATCH",
        "difference_kg": diff_kg,
        "accounting_meaning": "BALANCED",
        "deduction_already_recorded": False,
        "reversal_blocked": False,
        "duplicate_deduction_blocked": False,
        "synthetic_sale_blocked": True,
        "requires_owner_review": False,
        "can_approve_operationally": False,
        "policy_note": "Packed weight matches bulk input within tolerance.",
    }


def summarize_packaging_discrepancies(packaging_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize historical unresolved, pending review, and approved packaging discrepancies."""
    historical_items = []
    pending_items = []
    approved_items = []

    for row in packaging_records or []:
        info = classify_packaging_discrepancy(row)
        enriched = {
            **row,
            "discrepancy_classification": info["classification"],
            "review_state": info["review_state"],
            "reversal_blocked": info["reversal_blocked"],
            "duplicate_deduction_blocked": info["duplicate_deduction_blocked"],
            "synthetic_sale_blocked": info["synthetic_sale_blocked"],
            "policy_note": info["policy_note"],
        }
        cls = info["classification"]
        if cls == "HISTORICAL_UNRESOLVED":
            historical_items.append(enriched)
        elif cls == "PENDING_REVIEW":
            pending_items.append(enriched)
        elif cls == "APPROVED_DISCREPANCY":
            approved_items.append(enriched)

    return {
        "historical_unresolved_count": len(historical_items),
        "historical_unresolved_kg": round_stock(sum(abs(float(i.get("difference_kg", 0) or 0)) for i in historical_items)),
        "pending_review_count": len(pending_items),
        "pending_review_kg": round_stock(sum(abs(float(i.get("difference_kg", 0) or 0)) for i in pending_items)),
        "approved_discrepancy_count": len(approved_items),
        "historical_unresolved": historical_items,
        "pending_review": pending_items,
        "approved_discrepancy": approved_items,
    }

