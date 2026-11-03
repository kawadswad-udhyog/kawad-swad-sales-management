import unittest
from typing import Dict, Any, List, Optional


def resolve_workforce_field(
    row: Dict[str, Any],
    canonical_key: str,
    alias_keys: Optional[List[str]] = None,
    default: Any = None
) -> Any:
    """
    Strict, non-lossy field resolver for workforce records.
    
    Rules enforced:
    1. Canonical field takes absolute precedence if present and not empty string/None.
    2. Legitimate numeric zero (0, 0.0, False) is preserved and NEVER treated as missing.
    3. Blank strings ('') are treated as unpopulated only if an alias has a non-blank value.
    4. Conflicting populated values never merge; canonical value wins.
    5. Missing keys fall back to aliases in defined order, then default.
    """
    # Check canonical key
    if canonical_key in row:
        val = row[canonical_key]
        if val is not None:
            # Preserve numeric 0, 0.0, boolean False
            if isinstance(val, (int, float, bool)):
                return val
            if str(val).strip() != "":
                return val

    # Check alias keys in priority sequence
    if alias_keys:
        for ak in alias_keys:
            if ak in row:
                val = row[ak]
                if val is not None:
                    if isinstance(val, (int, float, bool)):
                        return val
                    if str(val).strip() != "":
                        return val

    # If canonical was present as empty string or None and no alias had content, return canonical
    if canonical_key in row and row[canonical_key] is not None:
        return row[canonical_key]

    return default


class TestWorkforceAliasAdapter(unittest.TestCase):

    def test_preserves_numeric_zero(self):
        """Zero values (e.g., 0 bonus, 0 deduction, 0 basic) must NEVER evaluate to missing/fallback."""
        # Row has canonical basic_salary = 0.0, alias base_salary = 25000.0
        row = {"basic_salary": 0.0, "base_salary": 25000.0}
        resolved = resolve_workforce_field(row, "basic_salary", ["base_salary"], default=10000.0)
        self.assertEqual(resolved, 0.0, "Numeric zero must take precedence and not fall back to alias")

        # Integer zero
        row_int = {"pf_deduction": 0, "epf_deduction": 1800}
        resolved_int = resolve_workforce_field(row_int, "pf_deduction", ["epf_deduction"], default=500)
        self.assertEqual(resolved_int, 0, "Integer zero must be preserved")

    def test_handles_blank_string_fallback(self):
        """Blank string in canonical falls back to populated alias."""
        row = {"attendance_date": "", "date": "2026-02-01"}
        resolved = resolve_workforce_field(row, "attendance_date", ["date", "att_date"], default="")
        self.assertEqual(resolved, "2026-02-01")

        # Whitespace-only string
        row_ws = {"attendance_date": "   ", "att_date": "2026-02-02"}
        resolved_ws = resolve_workforce_field(row_ws, "attendance_date", ["date", "att_date"], default="")
        self.assertEqual(resolved_ws, "2026-02-02")

    def test_missing_canonical_uses_alias(self):
        """Missing canonical key cleanly uses alias."""
        row = {"user_id": "USR-001"}
        resolved = resolve_workforce_field(row, "employee_id", ["user_id"], default="")
        self.assertEqual(resolved, "USR-001")

    def test_conflicting_populated_values_canonical_wins(self):
        """When canonical and alias are both populated with different values, canonical wins without merging."""
        row = {
            "basic_salary": 30000.0,
            "base_salary": 35000.0
        }
        resolved = resolve_workforce_field(row, "basic_salary", ["base_salary"], default=0.0)
        self.assertEqual(resolved, 30000.0, "Canonical must win over alias without merging")

    def test_all_missing_returns_default(self):
        """When neither canonical nor alias is in row, default is returned."""
        row = {"other_col": "value"}
        resolved = resolve_workforce_field(row, "basic_salary", ["base_salary", "basic"], default=0.0)
        self.assertEqual(resolved, 0.0)


if __name__ == "__main__":
    unittest.main()
