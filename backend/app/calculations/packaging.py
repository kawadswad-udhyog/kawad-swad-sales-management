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
