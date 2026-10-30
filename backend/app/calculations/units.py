"""
Authoritative Canonical Units & Precision Engine
Guarantees consistent unit normalization and precise arithmetic across all modules.
"""

import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional, Tuple, Union

# Authoritative stock units per category
CANONICAL_UNITS = {
    "FLOUR": "kg",
    "SPICE": "kg",
    "SALT": "kg",
    "OIL": "L",
    "WATER": "L",
    "PACKET": "packet",
    "RAW_MATERIAL": "kg",
}

# Precision standards
STOCK_PRECISION = Decimal("0.001")     # 3 decimals (1 gram precision for kg)
MONEY_PRECISION = Decimal("0.01")      # 2 decimals (paise precision)
RATIO_PRECISION = Decimal("0.0001")    # 4 decimals for formulation ratios and yields

MASS_UNITS = {"g", "gram", "grams", "kg", "kilogram", "kilograms", "kgs", "quintal", "ton"}
VOLUME_UNITS = {"ml", "milliliter", "millilitre", "milliliters", "millilitres", "l", "liter", "litre", "liters", "litres"}
COUNT_UNITS = {"packet", "packets", "pkt", "pkts", "piece", "pieces", "box", "boxes"}


def clean_currency_string(val: Any) -> str:
    """Normalize currency and numeric strings by removing currency symbols and thousand separators."""
    if val is None:
        return "0"
    s = str(val).strip()
    if not s:
        return "0"
    # Remove currency symbols (₹, $, €, £) and abbreviations (Rs., Rs, INR) case-insensitively
    s = re.sub(r'(?i)[₹$€£]|rs\.?|inr', '', s).strip()
    # Remove thousand comma separators
    s = s.replace(',', '').strip()
    if not s or s == "-":
        return "0"
    return s


def to_decimal(val: Union[float, int, str, Decimal]) -> Decimal:
    """Safely convert any numeric value or formatted currency string to Decimal without float representation noise."""
    if isinstance(val, Decimal):
        return val
    if val is None or str(val).strip() == "":
        return Decimal("0")
    try:
        clean_s = clean_currency_string(val)
        return Decimal(clean_s)
    except Exception as e:
        raise ValueError(f"Invalid numeric value '{val}': {e}")


def round_stock(val: Union[float, int, str, Decimal]) -> float:
    """Round to 3 decimal places for stock quantities."""
    dec = to_decimal(val)
    return float(dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))


def round_money(val: Union[float, int, str, Decimal]) -> float:
    """Round to 2 decimal places for financial amounts."""
    dec = to_decimal(val)
    return float(dec.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP))


def round_ratio(val: Union[float, int, str, Decimal]) -> float:
    """Round to 4 decimal places for yield ratios."""
    dec = to_decimal(val)
    return float(dec.quantize(RATIO_PRECISION, rounding=ROUND_HALF_UP))


def parse_currency_amount(val: Any) -> float:
    """
    Safely parse financial amounts from Google Sheets or API payloads into float.
    Handles numbers, currency symbols ('₹100.00', '₹ 1,200.50', 'Rs. 500', 'INR 250'),
    empty values, and thousand separators.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float, Decimal)):
        try:
            return round_money(val)
        except Exception:
            return float(val)
    return round_money(val)


def normalize_to_canonical_unit(
    quantity: Union[float, int, str, Decimal],
    from_unit: str,
    density_kg_per_l: Optional[float] = None,
) -> Tuple[float, str]:
    """
    Convert supported units into their canonical stock unit (kg for mass, L for volume).
    Rejects incompatible dimensional conversions.
    """
    qty_dec = to_decimal(quantity)
    if qty_dec < 0:
        raise ValueError(f"Quantity cannot be negative: {quantity}")

    u = str(from_unit or "").strip().lower()
    if not u:
        raise ValueError("Unit cannot be empty")

    # Mass units -> kg
    if u in {"g", "gram", "grams"}:
        return float((qty_dec / Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "kg"
    if u in {"kg", "kilogram", "kilograms", "kgs"}:
        return float(qty_dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "kg"
    if u in {"quintal"}:
        return float((qty_dec * Decimal("100")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "kg"

    # Volume units -> L
    if u in {"ml", "milliliter", "millilitre", "milliliters", "millilitres"}:
        return float((qty_dec / Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "L"
    if u in {"l", "liter", "litre", "liters", "litres"}:
        return float(qty_dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "L"

    # Count units
    if u in COUNT_UNITS:
        return int(qty_dec), "packet"

    # If cross-dimensional mass <-> volume conversion is requested, density must be provided
    if density_kg_per_l is not None and density_kg_per_l > 0:
        density_dec = to_decimal(density_kg_per_l)
        if u in MASS_UNITS:
            # mass to volume: L = kg / density
            kg_val, _ = normalize_to_canonical_unit(quantity, from_unit)
            return float((to_decimal(kg_val) / density_dec).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "L"
        if u in VOLUME_UNITS:
            # volume to mass: kg = L * density
            l_val, _ = normalize_to_canonical_unit(quantity, from_unit)
            return float((to_decimal(l_val) * density_dec).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), "kg"

    # Return standard unit if no special conversion rule matched
    return float(qty_dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP)), from_unit


def convert_unit(
    quantity: Union[float, int, str, Decimal],
    from_unit: str,
    to_unit: str,
    density_kg_per_l: Optional[float] = None,
) -> float:
    """
    Convert a quantity between compatible units.
    Raises ValueError if conversion is dimensionally incompatible or unsupported.
    """
    fu = str(from_unit or "").strip().lower()
    tu = str(to_unit or "").strip().lower()

    if fu == tu:
        return round_stock(quantity)

    # Check dimensional compatibility
    from_is_mass = fu in MASS_UNITS
    to_is_mass = tu in MASS_UNITS
    from_is_vol = fu in VOLUME_UNITS
    to_is_vol = tu in VOLUME_UNITS

    if from_is_mass and to_is_vol:
        if density_kg_per_l is None or density_kg_per_l <= 0:
            raise ValueError(
                f"Dimensionally incompatible conversion from '{from_unit}' to '{to_unit}' "
                "without a valid positive density factor."
            )
        kg_val, _ = normalize_to_canonical_unit(quantity, from_unit)
        l_val = to_decimal(kg_val) / to_decimal(density_kg_per_l)
        if tu in {"ml", "milliliter", "millilitre"}:
            return float((l_val * Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))
        return float(l_val.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))

    if from_is_vol and to_is_mass:
        if density_kg_per_l is None or density_kg_per_l <= 0:
            raise ValueError(
                f"Dimensionally incompatible conversion from '{from_unit}' to '{to_unit}' "
                "without a valid positive density factor."
            )
        l_val, _ = normalize_to_canonical_unit(quantity, from_unit)
        kg_val = to_decimal(l_val) * to_decimal(density_kg_per_l)
        if tu in {"g", "gram", "grams"}:
            return float((kg_val * Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))
        return float(kg_val.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))

    # Convert to canonical first
    can_val, can_unit = normalize_to_canonical_unit(quantity, from_unit)

    # Convert from canonical to target
    can_dec = to_decimal(can_val)
    if tu in {"g", "gram", "grams"}:
        if can_unit != "kg":
            raise ValueError(f"Cannot convert '{from_unit}' ({can_unit}) to grams")
        return float((can_dec * Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))
    if tu in {"kg", "kilogram", "kilograms", "kgs"}:
        if can_unit != "kg":
            raise ValueError(f"Cannot convert '{from_unit}' ({can_unit}) to kilograms")
        return float(can_dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))
    if tu in {"ml", "milliliter", "millilitre"}:
        if can_unit != "L":
            raise ValueError(f"Cannot convert '{from_unit}' ({can_unit}) to millilitres")
        return float((can_dec * Decimal("1000")).quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))
    if tu in {"l", "liter", "litre"}:
        if can_unit != "L":
            raise ValueError(f"Cannot convert '{from_unit}' ({can_unit}) to litres")
        return float(can_dec.quantize(STOCK_PRECISION, rounding=ROUND_HALF_UP))

    return round_stock(can_val)
