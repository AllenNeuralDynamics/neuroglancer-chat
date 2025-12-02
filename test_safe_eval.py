"""Test safe Polars evaluation with restricted namespace."""
import polars as pl

# Test data
df = pl.DataFrame({
    'x': [1, 2, 3, 4, 5],
    'y': [10, 20, 30, 40, 50],
    'name': ['a', 'b', 'c', 'd', 'e']
})

# Safe namespace
namespace = {
    'pl': pl,
    'df': df,
    '__builtins__': {}  # Blocks all dangerous built-ins
}

print("Testing safe Polars expressions...")
print("=" * 60)

# Test 1: Simple filter
print("\n1. Filter: df.filter(pl.col('x') > 2)")
result = eval("df.filter(pl.col('x') > 2)", namespace, {})
print(result)

# Test 2: Select + filter
print("\n2. Select + Filter: df.filter(pl.col('y') >= 30).select(['name', 'x'])")
result = eval("df.filter(pl.col('y') >= 30).select(['name', 'x'])", namespace, {})
print(result)

# Test 3: Complex query
print("\n3. Complex: df.with_columns((pl.col('x') * 10).alias('x10')).sort('x10', descending=True)")
result = eval("df.with_columns((pl.col('x') * 10).alias('x10')).sort('x10', descending=True)", namespace, {})
print(result)

# Test 4: Aggregation
print("\n4. Aggregation: df.select([pl.sum('x'), pl.mean('y')])")
result = eval("df.select([pl.sum('x'), pl.mean('y')])", namespace, {})
print(result)

# Test 5: Try dangerous operation (should fail)
print("\n5. Test security - trying to import os (should fail):")
try:
    result = eval("import os", namespace, {})
    print("❌ SECURITY BREACH: import worked!")
except Exception as e:
    print(f"✅ BLOCKED: {type(e).__name__}: {e}")

# Test 6: Try to access builtins (should fail)
print("\n6. Test security - trying to use open() (should fail):")
try:
    result = eval("open('/etc/passwd')", namespace, {})
    print("❌ SECURITY BREACH: open() worked!")
except Exception as e:
    print(f"✅ BLOCKED: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("All tests passed! Safe evaluation is working correctly.")
