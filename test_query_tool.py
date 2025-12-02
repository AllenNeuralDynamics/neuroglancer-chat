"""Test the data_query_polars tool directly."""
import polars as pl

# Simulate what the tool does
df = pl.DataFrame({
    'cell_id': [1, 2, 3, 4, 5],
    'x': [10, 20, 30, 40, 50],
    'y': [100, 200, 300, 400, 500]
})

print("Testing data_query_polars expressions...")
print("=" * 60)

# Test 1: Simple filter (should work)
print("\n1. Filter: df.filter(pl.col('cell_id') > 2)")
namespace = {'pl': pl, 'df': df, '__builtins__': {}}
try:
    result = eval("df.filter(pl.col('cell_id') > 2)", namespace, {})
    print(f"✅ Result type: {type(result)}")
    print(result)
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Aggregation with select (should work)
print("\n2. Aggregation: df.select([pl.max('cell_id')])")
try:
    result = eval("df.select([pl.max('cell_id')])", namespace, {})
    print(f"✅ Result type: {type(result)}")
    print(result)
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Direct max (returns scalar - now should work with our fix)
print("\n3. Direct max: df['cell_id'].max()")
try:
    result = eval("df['cell_id'].max()", namespace, {})
    print(f"✅ Result type: {type(result)}")
    print(f"Value: {result}")
    # Test wrapping it
    if isinstance(result, (int, float)):
        wrapped = pl.DataFrame({"result": [result]})
        print(f"Wrapped in DataFrame: {wrapped}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 4: Series max (should work with our fix)
print("\n4. Series operation: df.max()")
try:
    result = eval("df.max()", namespace, {})
    print(f"✅ Result type: {type(result)}")
    print(result)
    if isinstance(result, pl.Series):
        wrapped = pl.DataFrame({result.name or "value": result})
        print(f"Converted to DataFrame: {wrapped}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 60)
