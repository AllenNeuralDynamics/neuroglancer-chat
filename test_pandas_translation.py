"""Test pandas to Polars auto-translation."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from neurogabber.backend.main import _translate_pandas_to_polars

print("=" * 70)
print("Testing pandas → Polars auto-translation")
print("=" * 70)

test_cases = [
    # groupby → group_by
    ("df.groupby('cell_id').agg(pl.first('x'))", 
     "df.group_by('cell_id').agg(pl.first('x'))"),
    
    # distinct → unique
    ("df.select(pl.col('gene').distinct())",
     "df.select(pl.col('gene').unique())"),
    
    # reverse=True → descending=True
    ("df.sort('volume', reverse=True)",
     "df.sort('volume', descending=True)"),
    
    # Multiple translations
    ("df.groupby('cluster').agg(pl.max('val')).sort('val', reverse=False)",
     "df.group_by('cluster').agg(pl.max('val')).sort('val', descending=False)"),
    
    # Already correct (should not change)
    ("df.group_by('cell_id').agg(pl.first('x'))",
     "df.group_by('cell_id').agg(pl.first('x'))"),
]

all_passed = True
for i, (input_expr, expected) in enumerate(test_cases, 1):
    result = _translate_pandas_to_polars(input_expr)
    passed = result == expected
    all_passed = all_passed and passed
    
    print(f"\nTest {i}: {'✅ PASS' if passed else '❌ FAIL'}")
    print(f"  Input:    {input_expr}")
    print(f"  Expected: {expected}")
    print(f"  Got:      {result}")

print("\n" + "=" * 70)
if all_passed:
    print("✅ All tests passed!")
else:
    print("❌ Some tests failed")
print("=" * 70)
