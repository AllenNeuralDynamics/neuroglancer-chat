"""Test smart column truncation for wide tables."""
from neurogabber.panel.panel_app import _truncate_table_columns

# Test with a wide table
wide_table = """Query results:

| id | cell_id | x | y | z | mean_intensity | max_intensity | volume | area | perimeter | circularity | eccentricity | cluster | marker | View |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 200 | 10 | 5 | 5.5 | 7.2 | 1000 | 500 | 80 | 0.9 | 0.3 | A | Pvalb | [view](https://ng.app#!v1) |
| 2 | 110 | 210 | 20 | 6 | 6.5 | 8.1 | 1100 | 520 | 82 | 0.85 | 0.35 | B | Sst | [view](https://ng.app#!v2) |
| 3 | 120 | 220 | 30 | 7 | 7.5 | 9.0 | 1200 | 540 | 84 | 0.88 | 0.32 | A | Vip | [view](https://ng.app#!v3) |

Total: 3 cells."""

print("ORIGINAL TABLE:")
print("=" * 80)
print(wide_table)
print("\n" + "=" * 80)

truncated, was_truncated, all_cols = _truncate_table_columns(wide_table, max_cols=5)

print(f"\nWAS TRUNCATED: {was_truncated}")
print(f"ALL COLUMNS ({len(all_cols)}): {all_cols}")
print("\nTRUNCATED TABLE:")
print("=" * 80)
print(truncated)
print("\n" + "=" * 80)

# Count columns in output
if truncated:
    lines = truncated.split("\n")
    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            print(f"\nColumns shown: {len(parts)}")
            print(f"Column names: {parts}")
            break

# Test with narrow table (should not truncate)
print("\n\n" + "=" * 80)
print("TEST 2: Narrow table (should NOT truncate)")
print("=" * 80)

narrow_table = """Results:

| id | x | y | z | value | View |
|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 200 | 10 | 5.5 | [view](https://ng.app#!v1) |
| 2 | 110 | 210 | 20 | 6.5 | [view](https://ng.app#!v2) |

Done."""

truncated2, was_truncated2, all_cols2 = _truncate_table_columns(narrow_table, max_cols=5)
print(f"\nWAS TRUNCATED: {was_truncated2} (should be False)")
print(f"ALL COLUMNS: {all_cols2}")
