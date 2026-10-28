"""
Kawad Swad Papad Calculation Engine
Authoritative centralized calculation layer for:
- Canonical unit conversions and precision
- Recipe scaling, yield calculation, and formulation validation
- Production batch lifecycle, material issue, and variance reconciliation
- Packaging weight derivation, loss recording, and discrepancy blocking
- Batch costing, purchase rate snapshots, and SKU cost allocation
- Inventory ledger math and transaction recovery
"""

from .units import (
    normalize_to_canonical_unit,
    convert_unit,
    CANONICAL_UNITS,
    STOCK_PRECISION,
    MONEY_PRECISION,
    RATIO_PRECISION,
    round_stock,
    round_money,
    round_ratio,
    to_decimal,
)
from .recipes import (
    scale_recipe,
    validate_recipe_formulation,
    calculate_recipe_cost_estimate,
)
from .production import (
    calculate_production_requirements,
    reconcile_production_output,
)
from .packaging import (
    calculate_packed_weight,
    calculate_packing_variance,
    validate_packing_discrepancy,
    DEFAULT_PACKING_TOLERANCE_KG,
)
from .costing import (
    get_latest_purchase_rate,
    calculate_batch_actual_cost,
    calculate_finished_sku_cost,
)
from .inventory import (
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_warehouse_stock_balance,
    calculate_salesman_stock_balance,
    calculate_physical_count_variance,
    calculate_raw_material_balance,
    calculate_consolidated_finished_goods_register,
)

__all__ = [
    "normalize_to_canonical_unit",
    "convert_unit",
    "CANONICAL_UNITS",
    "STOCK_PRECISION",
    "MONEY_PRECISION",
    "RATIO_PRECISION",
    "round_stock",
    "round_money",
    "round_ratio",
    "scale_recipe",
    "validate_recipe_formulation",
    "calculate_recipe_cost_estimate",
    "calculate_production_requirements",
    "reconcile_production_output",
    "calculate_packed_weight",
    "calculate_packing_variance",
    "validate_packing_discrepancy",
    "DEFAULT_PACKING_TOLERANCE_KG",
    "get_latest_purchase_rate",
    "calculate_batch_actual_cost",
    "calculate_finished_sku_cost",
    "calculate_bulk_stock_balance",
    "calculate_finished_stock_balance",
    "calculate_warehouse_stock_balance",
    "calculate_salesman_stock_balance",
    "calculate_physical_count_variance",
    "calculate_raw_material_balance",
    "calculate_consolidated_finished_goods_register",
]
