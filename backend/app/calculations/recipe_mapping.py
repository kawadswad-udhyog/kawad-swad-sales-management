"""
Deterministic Product-to-Recipe Mapping Engine for Kawad Swad ERP (REG-03: CALC-009 to CALC-011).

Resolves finished SKU / product master rows (including PRD-0001 sequential IDs,
pack-size SKU variants like 200g/500g/1000g and legacy 250g/400g historical SKUs, and bulk names)
to the authoritative recipe record without naive substring collisions.
See: docs/CALCULATION_REGISTER_REG03.md
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class AmbiguousRecipeMappingError(ValueError):
    """Raised when more than one conflicting recipe/formula matches a product."""

    def __init__(self, message: str, candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.candidates = candidates or []


class MissingRecipeMappingError(ValueError):
    """Raised when no valid/approved recipe can be resolved for a product."""

    def __init__(self, message: str, unapproved_candidates: Optional[List[str]] = None):
        super().__init__(message)
        self.unapproved_candidates = unapproved_candidates or []


# Explicit canonical mapping from known Product IDs / SKUs to authoritative Master Recipe IDs.
# Does not mutate Google Sheets master data or recipe formulations.
CANONICAL_PRODUCT_RECIPE_MAP: Dict[str, str] = {
    # Moong Master family
    "PRD-MOONG-MASTER": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-200": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-200G": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-400": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-400G": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-500": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-500G": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-1000": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-1000G": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG-BULK": "RCP-MOONG-MASTER-V2",
    "PRD-MOONG": "RCP-MOONG-MASTER-V2",
    "PRD-M-200": "RCP-MOONG-MASTER-V2",
    "PRD-M-500": "RCP-MOONG-MASTER-V2",
    "PRD-M-1000": "RCP-MOONG-MASTER-V2",
    "KS-MP-200": "RCP-MOONG-MASTER-V2",
    "KS-MP-500": "RCP-MOONG-MASTER-V2",
    "KS-MP-1000": "RCP-MOONG-MASTER-V2",
    "KS-MM-200": "RCP-MOONG-MASTER-V2",
    "KS-MM-500": "RCP-MOONG-MASTER-V2",
    "KS-MM-1000": "RCP-MOONG-MASTER-V2",
    "MOONG-200G": "RCP-MOONG-MASTER-V2",
    "MOONG-400G": "RCP-MOONG-MASTER-V2",
    "MOONG-500G": "RCP-MOONG-MASTER-V2",
    "MOONG-1000G": "RCP-MOONG-MASTER-V2",
    # Moong Variants
    "PRD-MOONG-GARLIC": "RCP-MOONG-GARLIC-V2",
    "PRD-GARLIC-200G": "RCP-MOONG-GARLIC-V2",
    "PRD-GARLIC-500G": "RCP-MOONG-GARLIC-V2",
    "MOONG-GARLIC-200G": "RCP-MOONG-GARLIC-V2",
    "MOONG-GARLIC-500G": "RCP-MOONG-GARLIC-V2",
    "PRD-MOONG-JEERA": "RCP-MOONG-JEERA-V2",
    "MOONG-JEERA-200G": "RCP-MOONG-JEERA-V2",
    "MOONG-JEERA-500G": "RCP-MOONG-JEERA-V2",
    "PRD-MOONG-PUDHINA": "RCP-MOONG-PUDHINA-V2",
    "MOONG-PUDHINA-200G": "RCP-MOONG-PUDHINA-V2",
    "MOONG-PUDHINA-500G": "RCP-MOONG-PUDHINA-V2",
    "PRD-MOONG-GREENCHILLI": "RCP-MOONG-GREENCHILLI-V2",
    "MOONG-GREENCHILLI-200G": "RCP-MOONG-GREENCHILLI-V2",
    "MOONG-GREENCHILLI-500G": "RCP-MOONG-GREENCHILLI-V2",
    "PRD-MOONG-KASURI": "RCP-MOONG-KASURI-V2",
    "MOONG-KASURI-200G": "RCP-MOONG-KASURI-V2",
    "MOONG-KASURI-500G": "RCP-MOONG-KASURI-V2",
    "PRD-MOONG-PUNJABI": "RCP-MOONG-PUNJABI-V2",
    "MOONG-PUNJABI-200G": "RCP-MOONG-PUNJABI-V2",
    "MOONG-PUNJABI-500G": "RCP-MOONG-PUNJABI-V2",
    "PRD-MOONG-KHATAMEETHA": "RCP-MOONG-KHATAMEETHA-V2",
    "PRD-MOONG-KM-200": "RCP-MOONG-KHATAMEETHA-V2",
    "PRD-MOONG-KM-500": "RCP-MOONG-KHATAMEETHA-V2",
    "MOONG-KM-200G": "RCP-MOONG-KHATAMEETHA-V2",
    "MOONG-KM-500G": "RCP-MOONG-KHATAMEETHA-V2",
    # Chana Family
    "PRD-CHANA-CHOTU": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-MASALA": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-BULK": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-200": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-250": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-500": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-1000": "RCP-CHANA-CHOTU-V2",
    "CHANA-250G": "RCP-CHANA-CHOTU-V2",
    "CHANA-500G": "RCP-CHANA-CHOTU-V2",
    "CHANA-1000G": "RCP-CHANA-CHOTU-V2",
    "PRD-CHANA-GARLIC": "RCP-CHANA-GARLIC-V2",
    "CHANA-GARLIC-250G": "RCP-CHANA-GARLIC-V2",
    "CHANA-GARLIC-500G": "RCP-CHANA-GARLIC-V2",
    "PRD-CHANA-KHATAMITHA": "RCP-CHANA-KHATAMITHA-V2",
    "CHANA-KM-250G": "RCP-CHANA-KHATAMITHA-V2",
    "CHANA-KM-500G": "RCP-CHANA-KHATAMITHA-V2",
    "PRD-CHANA-TOMATO": "RCP-CHANA-TOMATO-V2",
    "CHANA-TOMATO-250G": "RCP-CHANA-TOMATO-V2",
    "CHANA-TOMATO-500G": "RCP-CHANA-TOMATO-V2",
    "PRD-CHANA-PUNJABI": "RCP-CHANA-PUNJABI-V2",
    "CHANA-PUNJABI-250G": "RCP-CHANA-PUNJABI-V2",
    "CHANA-PUNJABI-500G": "RCP-CHANA-PUNJABI-V2",
    # Urad Family
    "PRD-URAD-GURU": "RCP-URAD-GURU-V2",
    "PRD-URAD-200": "RCP-URAD-GURU-V2",
    "PRD-URAD-500": "RCP-URAD-GURU-V2",
    "URAD-200G": "RCP-URAD-GURU-V2",
    "URAD-500G": "RCP-URAD-GURU-V2",
    "PRD-URAD-GARLIC": "RCP-URAD-GARLIC-V2",
    "URAD-GARLIC-200G": "RCP-URAD-GARLIC-V2",
    "URAD-GARLIC-500G": "RCP-URAD-GARLIC-V2",
}

# Canonical normalized base names -> recipe_id
_CANONICAL_NAME_TO_RECIPE: Dict[str, str] = {
    "moong master papad": "RCP-MOONG-MASTER-V2",
    "moong special papad": "RCP-MOONG-MASTER-V2",
    "moong standard papad": "RCP-MOONG-MASTER-V2",
    "moong papad": "RCP-MOONG-MASTER-V2",
    "moong garlic papad": "RCP-MOONG-GARLIC-V2",
    "moong jeera papad": "RCP-MOONG-JEERA-V2",
    "moong pudhina papad": "RCP-MOONG-PUDHINA-V2",
    "moong pudina papad": "RCP-MOONG-PUDHINA-V2",
    "moong green chilli papad": "RCP-MOONG-GREENCHILLI-V2",
    "moong kasuri methi papad": "RCP-MOONG-KASURI-V2",
    "moong punjabi masala papad": "RCP-MOONG-PUNJABI-V2",
    "moong khata meetha papad": "RCP-MOONG-KHATAMEETHA-V2",
    "moong khatta meetha papad": "RCP-MOONG-KHATAMEETHA-V2",
    "moong khata mitha papad": "RCP-MOONG-KHATAMEETHA-V2",
    "chana chotu papad": "RCP-CHANA-CHOTU-V2",
    "chana masala papad": "RCP-CHANA-CHOTU-V2",
    "chana garlic papad": "RCP-CHANA-GARLIC-V2",
    "chana khata mitha papad": "RCP-CHANA-KHATAMITHA-V2",
    "chana khatta meetha papad": "RCP-CHANA-KHATAMITHA-V2",
    "chana tomato papad": "RCP-CHANA-TOMATO-V2",
    "chana punjabi masala papad": "RCP-CHANA-PUNJABI-V2",
    "urad guru papad": "RCP-URAD-GURU-V2",
    "urad punjabi tadka papad": "RCP-URAD-GURU-V2",
    "urad garlic papad": "RCP-URAD-GARLIC-V2",
}

_FAMILY_VARIANT_TO_RECIPE: Dict[Tuple[str, str], str] = {
    ("MOONG", "MASTER"): "RCP-MOONG-MASTER-V2",
    ("MOONG", "SPECIAL"): "RCP-MOONG-MASTER-V2",
    ("MOONG", "STANDARD"): "RCP-MOONG-MASTER-V2",
    ("MOONG", "GARLIC"): "RCP-MOONG-GARLIC-V2",
    ("MOONG", "JEERA"): "RCP-MOONG-JEERA-V2",
    ("MOONG", "PUDHINA"): "RCP-MOONG-PUDHINA-V2",
    ("MOONG", "PUDINA"): "RCP-MOONG-PUDHINA-V2",
    ("MOONG", "GREEN CHILLI"): "RCP-MOONG-GREENCHILLI-V2",
    ("MOONG", "KASURI METHI"): "RCP-MOONG-KASURI-V2",
    ("MOONG", "PUNJABI MASALA"): "RCP-MOONG-PUNJABI-V2",
    ("MOONG", "KHATA MEETHA"): "RCP-MOONG-KHATAMEETHA-V2",
    ("MOONG", "KHATTA MEETHA"): "RCP-MOONG-KHATAMEETHA-V2",
    ("MOONG", "KHATA MITHA"): "RCP-MOONG-KHATAMEETHA-V2",
    ("CHANA", "CHOTU"): "RCP-CHANA-CHOTU-V2",
    ("CHANA", "MASALA"): "RCP-CHANA-CHOTU-V2",
    ("CHANA", "SPICY MASALA"): "RCP-CHANA-CHOTU-V2",
    ("CHANA", "GARLIC"): "RCP-CHANA-GARLIC-V2",
    ("CHANA", "KHATA MITHA"): "RCP-CHANA-KHATAMITHA-V2",
    ("CHANA", "KHATTA MEETHA"): "RCP-CHANA-KHATAMITHA-V2",
    ("CHANA", "TOMATO"): "RCP-CHANA-TOMATO-V2",
    ("CHANA", "PUNJABI MASALA"): "RCP-CHANA-PUNJABI-V2",
    ("URAD", "GURU"): "RCP-URAD-GURU-V2",
    ("URAD", "PUNJABI TADKA"): "RCP-URAD-GURU-V2",
    ("URAD", "GARLIC"): "RCP-URAD-GARLIC-V2",
}

_PACK_WEIGHT_RE = re.compile(r"(?:\(|\b)(?:100|150|200|250|400|500|1000)\s*(?:g|gm|gms|gram|grams)\b\)?|(?:\(|\b)[12]\s*kg\b\)?", re.IGNORECASE)
_CODE_WEIGHT_RE = re.compile(r"-(?:100|150|200|250|400|500|1000)G?$", re.IGNORECASE)


def _is_truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in {"true", "1", "yes", "y", "approved"}


def _recipe_is_approved(recipe: Dict[str, Any]) -> bool:
    if "approved" in recipe and _is_truthy(recipe.get("approved")):
        return True
    status = str(recipe.get("status", "")).strip().upper()
    return status == "APPROVED"


def _recipe_version(recipe: Dict[str, Any]) -> float:
    try:
        return float(recipe.get("version") or 0)
    except Exception:
        return 0.0


def normalize_product_base_name(name: str) -> str:
    """[CALC-009a] Strip pack sizes, weight tokens, and normalize spacing/punctuation."""
    raw = str(name or "").strip().lower()
    if not raw:
        return ""
    cleaned = _PACK_WEIGHT_RE.sub(" ", raw)
    cleaned = cleaned.replace("(", " ").replace(")", " ").replace("-", " ").replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def strip_sku_pack_suffix(code: str) -> str:
    """[CALC-009b] Strip trailing pack-weight suffix (e.g., -200G, -500G, -1000G) from SKU/product code."""
    raw = str(code or "").strip().upper()
    if not raw:
        return ""
    return _CODE_WEIGHT_RE.sub("", raw)


def _formula_group_key(recipe: Dict[str, Any]) -> str:
    """Group multiple versions of the same formula together so versioning isn't flagged as conflict."""
    rid = str(recipe.get("recipe_id", "")).strip().upper()
    # Strip trailing -V2 / -V3 suffix if present, or use base name
    rid_base = re.sub(r"-V\d+(?:\.\d+)?$", "", rid)
    if rid_base:
        return rid_base
    return normalize_product_base_name(str(recipe.get("product_name_snapshot") or recipe.get("product_name") or ""))


def _merge_recipe_sources(
    recipes_records: List[Dict[str, Any]],
    master_recipes: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Return (sheet_recipes, master_fallback_recipes).
    Sheet records take precedence over hardcoded master definitions for matching recipe_id.
    """
    sheet_list = [dict(r) for r in (recipes_records or []) if isinstance(r, dict)]
    sheet_rids = {str(r.get("recipe_id", "")).strip().upper() for r in sheet_list if r.get("recipe_id")}
    master_list = []
    for m in (master_recipes or []):
        if not isinstance(m, dict):
            continue
        m_rid = str(m.get("recipe_id", "")).strip().upper()
        if m_rid and m_rid in sheet_rids:
            continue
        master_list.append(dict(m))
    return sheet_list, master_list


def _select_from_candidates(
    candidates: List[Dict[str, Any]],
    *,
    require_approved: bool,
    context_label: str,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    # Deduplicate exact same record references by recipe_id + version
    pool = candidates
    if require_approved:
        approved = [r for r in pool if _recipe_is_approved(r)]
        if not approved:
            unapproved_ids = sorted({str(r.get("recipe_id") or r.get("product_id") or "UNSPECIFIED") for r in pool})
            raise MissingRecipeMappingError(
                f"Recipe(s) {unapproved_ids} matched {context_label} but remain unapproved/DRAFT. Owner confirmation is required before production.",
                unapproved_candidates=unapproved_ids,
            )
        pool = approved

    # Check if distinct formula groups exist in the pool
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in pool:
        gkey = _formula_group_key(rec)
        groups.setdefault(gkey, []).append(rec)

    if len(groups) > 1:
        conflict_ids = sorted({str(r.get("recipe_id") or r.get("product_name_snapshot") or "UNKNOWN") for r in pool})
        raise AmbiguousRecipeMappingError(
            f"Ambiguous recipe mapping for {context_label}: multiple conflicting recipes matched ({', '.join(conflict_ids)}). Set an explicit recipe_id on the product or request.",
            candidates=conflict_ids,
        )

    # Single formula group -> return highest version (sheet records already take precedence via _merge_recipe_sources)
    ranked = sorted(pool, key=lambda r: (_recipe_version(r), 1 if _recipe_is_approved(r) else 0), reverse=True)
    return ranked[0]


def resolve_product_recipe(
    product: Optional[Dict[str, Any]],
    recipes_records: List[Dict[str, Any]],
    master_recipes: Optional[List[Dict[str, Any]]] = None,
    requested_recipe_id: Optional[str] = None,
    require_approved: bool = True,
) -> Dict[str, Any]:
    """
    [CALC-010] Deterministically resolve the single authoritative recipe for a product.

    Precedence:
      1. Explicit `requested_recipe_id` parameter.
      2. Explicit mapping field on the `product` row (`recipe_id`, `master_recipe_id`, `recipe_code`, `formula_key`, `master_product_id`).
      3. Direct `product_id` match in `Recipes` (then `master_recipes`).
      4. Canonical deterministic mapping dictionary on `product_id` / `sku` (and pack-suffix-stripped codes).
      5. Normalized base `product_name` (pack sizes stripped) or explicit `(product_family, variant)` structural match.
    """
    # Static template formulas are not production records.
    # Only persisted recipes or explicitly supplied data are eligible.
    if master_recipes is None:
        master_recipes = []

    sheet_recipes, master_fallback = _merge_recipe_sources(recipes_records, master_recipes)
    all_recipes = sheet_recipes + master_fallback

    prod = product or {}
    prod_id = str(prod.get("product_id", "")).strip()
    prod_sku = str(prod.get("sku", "")).strip()
    prod_name = str(prod.get("product_name", "")).strip()
    prod_variant = str(prod.get("variant", "")).strip()
    context_label = f"product '{prod_name or prod_id or 'UNKNOWN'}' ({prod_id or prod_sku or 'NO-ID'})"

    def _find_by_recipe_id(target_rid: str, source_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        clean = target_rid.strip().upper()
        return [r for r in source_list if str(r.get("recipe_id", "")).strip().upper() == clean]

    # Tier 1: Explicit requested_recipe_id
    if requested_recipe_id and str(requested_recipe_id).strip():
        req_rid = str(requested_recipe_id).strip()
        matches = _find_by_recipe_id(req_rid, sheet_recipes) or _find_by_recipe_id(req_rid, all_recipes)
        if not matches:
            raise MissingRecipeMappingError(f"Requested recipe '{req_rid}' was not found for {context_label}.")
        selected = _select_from_candidates(matches, require_approved=require_approved, context_label=f"{context_label} (requested {req_rid})")
        return {**selected, "mapping_source": "REQUESTED_RECIPE_ID"}

    # Tier 2: Explicit mapping column on Product record
    for field_key in ("recipe_id", "master_recipe_id", "recipe_code", "formula_key", "master_product_id"):
        explicit_val = str(prod.get(field_key) or "").strip()
        if not explicit_val:
            continue
        # Match either recipe_id or master product_id
        matches = _find_by_recipe_id(explicit_val, sheet_recipes) or _find_by_recipe_id(explicit_val, all_recipes)
        if not matches:
            matches = [
                r for r in all_recipes
                if str(r.get("product_id", "")).strip().upper() == explicit_val.upper()
            ]
        if not matches:
            raise MissingRecipeMappingError(
                f"Explicit product mapping '{field_key}={explicit_val}' on {context_label} does not match any recipe."
            )
        selected = _select_from_candidates(matches, require_approved=require_approved, context_label=f"{context_label} ({field_key}={explicit_val})")
        return {**selected, "mapping_source": f"PRODUCT_{field_key.upper()}"}

    # Tier 3: Direct product_id match in Recipes (sheet first, then master)
    if prod_id:
        pid_upper = prod_id.upper()
        sheet_pid_matches = [r for r in sheet_recipes if str(r.get("product_id", "")).strip().upper() == pid_upper]
        if sheet_pid_matches:
            selected = _select_from_candidates(sheet_pid_matches, require_approved=require_approved, context_label=context_label)
            return {**selected, "mapping_source": "DIRECT_PRODUCT_ID"}
        master_pid_matches = [r for r in master_fallback if str(r.get("product_id", "")).strip().upper() == pid_upper]
        if master_pid_matches:
            selected = _select_from_candidates(master_pid_matches, require_approved=require_approved, context_label=context_label)
            return {**selected, "mapping_source": "MASTER_PRODUCT_ID"}

    # Tier 4: Canonical SKU / Product ID deterministic mapping table
    code_candidates: List[str] = []
    for raw_code in (prod_id, prod_sku, strip_sku_pack_suffix(prod_id), strip_sku_pack_suffix(prod_sku)):
        upper_c = str(raw_code or "").strip().upper()
        if upper_c and upper_c in CANONICAL_PRODUCT_RECIPE_MAP:
            mapped_rid = CANONICAL_PRODUCT_RECIPE_MAP[upper_c]
            if mapped_rid not in code_candidates:
                code_candidates.append(mapped_rid)

    if len(code_candidates) > 1:
        raise AmbiguousRecipeMappingError(
            f"Ambiguous canonical code mapping for {context_label}: matched {', '.join(code_candidates)}.",
            candidates=code_candidates,
        )
    if len(code_candidates) == 1:
        target_rid = code_candidates[0]
        matches = _find_by_recipe_id(target_rid, sheet_recipes) or _find_by_recipe_id(target_rid, all_recipes)
        if matches:
            selected = _select_from_candidates(matches, require_approved=require_approved, context_label=context_label)
            return {**selected, "mapping_source": "CANONICAL_CODE_MAP"}

    # Tier 5a: Normalized base product_name equality against Recipes sheet & canonical names
    norm_name = normalize_product_base_name(prod_name)
    if norm_name:
        sheet_name_matches = [
            r for r in sheet_recipes
            if normalize_product_base_name(str(r.get("product_name_snapshot") or r.get("product_name") or "")) == norm_name
        ]
        if sheet_name_matches:
            selected = _select_from_candidates(sheet_name_matches, require_approved=require_approved, context_label=context_label)
            return {**selected, "mapping_source": "NORMALIZED_RECIPE_NAME"}

        if norm_name in _CANONICAL_NAME_TO_RECIPE:
            target_rid = _CANONICAL_NAME_TO_RECIPE[norm_name]
            matches = _find_by_recipe_id(target_rid, sheet_recipes) or _find_by_recipe_id(target_rid, all_recipes)
            if matches:
                selected = _select_from_candidates(matches, require_approved=require_approved, context_label=context_label)
                return {**selected, "mapping_source": "CANONICAL_NAME_MAP"}

        master_name_matches = [
            r for r in master_fallback
            if normalize_product_base_name(str(r.get("product_name_snapshot") or r.get("product_name") or "")) == norm_name
        ]
        if master_name_matches:
            selected = _select_from_candidates(master_name_matches, require_approved=require_approved, context_label=context_label)
            return {**selected, "mapping_source": "MASTER_NORMALIZED_NAME"}

    # Tier 5b: Structural (family + variant) deterministic lookup
    family_upper = ""
    for fam in ("MOONG", "CHANA", "URAD"):
        if re.search(rf"\b{fam}\b", norm_name.upper()) or fam in prod_sku.upper() or fam in prod_id.upper():
            if family_upper and family_upper != fam:
                raise AmbiguousRecipeMappingError(
                    f"Ambiguous product family for {context_label}: matches both {family_upper} and {fam}."
                )
            family_upper = fam

    if family_upper and prod_variant:
        var_upper = re.sub(r"\s+", " ", prod_variant.strip().upper())
        if (family_upper, var_upper) in _FAMILY_VARIANT_TO_RECIPE:
            target_rid = _FAMILY_VARIANT_TO_RECIPE[(family_upper, var_upper)]
            matches = _find_by_recipe_id(target_rid, sheet_recipes) or _find_by_recipe_id(target_rid, all_recipes)
            if matches:
                selected = _select_from_candidates(matches, require_approved=require_approved, context_label=context_label)
                return {**selected, "mapping_source": "FAMILY_VARIANT_MAP"}

    raise MissingRecipeMappingError(
        f"No deterministic recipe mapping exists for {context_label}. Assign an approved recipe_id before production."
    )


def audit_product_recipe_mappings(
    products_records: List[Dict[str, Any]],
    recipes_records: List[Dict[str, Any]],
    master_recipes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    [CALC-011] Read-only diagnostic audit of every product in Products against Recipes & Master Recipes.
    Returns per-product mapping status and summary counts. Never mutates sheets.
    """
    # Static template formulas are not production records.
    # Only persisted recipes or explicitly supplied data are eligible.
    if master_recipes is None:
        master_recipes = []

    items: List[Dict[str, Any]] = []
    counts = {
        "total_products": 0,
        "mapped_approved": 0,
        "mapped_draft": 0,
        "ambiguous": 0,
        "unmapped": 0,
    }

    for prod in products_records or []:
        pid = str(prod.get("product_id", "")).strip()
        if not pid:
            continue
        counts["total_products"] += 1
        pname = str(prod.get("product_name", "")).strip()
        sku = str(prod.get("sku", "")).strip()
        active_flag = str(prod.get("active", "true")).strip().lower() not in {"false", "0", "no"}

        entry: Dict[str, Any] = {
            "product_id": pid,
            "sku": sku,
            "product_name": pname,
            "pack_weight_g": prod.get("pack_weight_g", ""),
            "active": active_flag,
            "explicit_recipe_id": str(prod.get("recipe_id") or "").strip(),
            "resolved_recipe_id": None,
            "resolved_recipe_name": None,
            "recipe_approved": False,
            "mapping_source": None,
            "status": "UNMAPPED",
            "detail": "",
        }

        try:
            rec = resolve_product_recipe(
                product=prod,
                recipes_records=recipes_records,
                master_recipes=master_recipes,
                require_approved=False,
            )
            is_app = _recipe_is_approved(rec)
            entry["resolved_recipe_id"] = rec.get("recipe_id")
            entry["resolved_recipe_name"] = rec.get("product_name_snapshot") or rec.get("product_name")
            entry["recipe_approved"] = is_app
            entry["mapping_source"] = rec.get("mapping_source")
            entry["status"] = "MAPPED" if is_app else "MAPPED_DRAFT_RECIPE"
            entry["detail"] = (
                f"Deterministically mapped via {rec.get('mapping_source')}"
                if is_app
                else f"Mapped to {rec.get('recipe_id')} via {rec.get('mapping_source')} (awaiting Owner approval)"
            )
            if is_app:
                counts["mapped_approved"] += 1
            else:
                counts["mapped_draft"] += 1
        except AmbiguousRecipeMappingError as amb_err:
            entry["status"] = "AMBIGUOUS"
            entry["detail"] = str(amb_err)
            entry["candidates"] = amb_err.candidates
            counts["ambiguous"] += 1
        except MissingRecipeMappingError as miss_err:
            entry["status"] = "UNMAPPED"
            entry["detail"] = str(miss_err)
            counts["unmapped"] += 1

        items.append(entry)

    return {
        "summary": counts,
        "mappings": items,
    }
