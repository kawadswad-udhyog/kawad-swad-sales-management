"""
Authoritative Production Engine: Requirements & Output Reconciliation
Implements Part 2 and Part 4 of the specification.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from .units import (
    round_stock,
    round_ratio,
    to_decimal,
)
from .recipes import scale_recipe


def calculate_production_requirements(
    recipe: Dict[str, Any],
    planned_output_kg: float,
) -> Dict[str, Any]:
    """
    Calculate ingredient requirements for a planned finished dried papad output.
    """
    items = recipe.get("items") or []
    expected_yield_kg = float(recipe.get("expected_yield_kg", 1.2) or 1.2)
    flour_base_kg = float(recipe.get("flour_base_used_kg", 1.0) or 1.0)

    scaled = scale_recipe(
        recipe_items=items,
        expected_yield_kg=expected_yield_kg,
        planned_output_kg=planned_output_kg,
        reference_flour_base_kg=flour_base_kg,
    )
    return scaled


def reconcile_production_output(
    saleable_output_kg: float,
    gross_output_kg: Optional[float] = None,
    rejected_output_kg: float = 0.0,
    process_loss_kg: float = 0.0,
    flour_base_used_kg: Optional[float] = None,
    benchmark_yield_ratio: float = 1.2,
) -> Dict[str, Any]:
    """
    Reconcile actual production output:
    - saleable_output_kg: finished, dried, saleable papad.
    - rejected_output_kg: broken, misshapen, or non-saleable papad.
    - process_loss_kg: recorded wastage / drying shrinkage.
    - unexplained_variance_kg: difference between gross output and (saleable + rejected + loss).
    """
    if saleable_output_kg < 0:
        raise ValueError("Saleable output cannot be negative")
    if rejected_output_kg < 0:
        raise ValueError("Rejected output cannot be negative")
    if process_loss_kg < 0:
        raise ValueError("Process loss cannot be negative")

    saleable_dec = to_decimal(saleable_output_kg)
    rejected_dec = to_decimal(rejected_output_kg)
    loss_dec = to_decimal(process_loss_kg)

    # If gross output is not supplied, gross = saleable + rejected
    if gross_output_kg is None or gross_output_kg <= 0:
        gross_dec = saleable_dec + rejected_dec + loss_dec
    else:
        gross_dec = to_decimal(gross_output_kg)
        if gross_dec < (saleable_dec + rejected_dec):
            raise ValueError(
                f"Gross output ({gross_output_kg} kg) cannot be less than saleable ({saleable_output_kg} kg) "
                f"+ rejected output ({rejected_output_kg} kg)"
            )

    # Unexplained variance = gross - (saleable + rejected + process_loss)
    unexplained_variance_dec = gross_dec - (saleable_dec + rejected_dec + loss_dec)

    # Yield ratio calculation against flour base
    actual_yield_ratio = None
    expected_benchmark_kg = None
    yield_variance_kg = None

    if flour_base_used_kg is not None and flour_base_used_kg > 0:
        flour_dec = to_decimal(flour_base_used_kg)
        benchmark_dec = to_decimal(benchmark_yield_ratio)
        actual_yield_ratio = round_ratio(saleable_dec / flour_dec)
        expected_benchmark_kg = round_stock(flour_dec * benchmark_dec)
        yield_variance_kg = round_stock(saleable_dec - to_decimal(expected_benchmark_kg))

    return {
        "saleable_output_kg": round_stock(saleable_dec),
        "gross_output_kg": round_stock(gross_dec),
        "rejected_output_kg": round_stock(rejected_dec),
        "process_loss_kg": round_stock(loss_dec),
        "unexplained_variance_kg": round_stock(unexplained_variance_dec),
        "flour_base_used_kg": round_stock(flour_base_used_kg) if flour_base_used_kg else None,
        "actual_yield_ratio": actual_yield_ratio,
        "benchmark_yield_kg": expected_benchmark_kg,
        "yield_variance_kg": yield_variance_kg,
    }
