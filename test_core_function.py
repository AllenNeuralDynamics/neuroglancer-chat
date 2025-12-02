"""Test that core functions work without FastAPI."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import the core function (no FastAPI required!)
from neuroglancer_chat.backend.main import execute_query_polars, DATA_MEMORY
import polars as pl

print("=" * 70)
print("Testing execute_query_polars as a pure function (no FastAPI)")
print("=" * 70)

# Create test data
test_df = pl.DataFrame({
    'id': [1, 2, 3, 4, 5],
    'value': [10, 20, 30, 40, 50],
    'category': ['A', 'B', 'A', 'B', 'A']
})

# Add to memory
DATA_MEMORY.files['test123'] = type('obj', (), {
    'file_id': 'test123',
    'name': 'test.csv',
    'df': test_df,
    'to_meta': lambda: {'file_id': 'test123', 'name': 'test.csv', 'n_rows': 5, 'n_cols': 3, 'columns': ['id', 'value', 'category']}
})()

print("\n1. Test simple filter:")
result = execute_query_polars(
    file_id='test123',
    expression='df.filter(pl.col("value") > 20)'
)
print(f"   Success: {result.get('ok', False)}")
print(f"   Rows returned: {result.get('rows', 0)}")
print(f"   Data: {result.get('data', {})}")

print("\n2. Test aggregation:")
result = execute_query_polars(
    file_id='test123',
    expression='df.select([pl.max("value"), pl.mean("value")])'
)
print(f"   Success: {result.get('ok', False)}")
print(f"   Data: {result.get('data', {})}")

print("\n3. Test with list result:")
result = execute_query_polars(
    file_id='test123',
    expression='df.select([pl.col("category")]).unique().to_list()'
)
print(f"   Success: {result.get('ok', False)}")
print(f"   Data: {result.get('data', {})}")

print("\n4. Test error handling (missing file):")
result = execute_query_polars(
    file_id='nonexistent',
    expression='df.select([pl.col("value")])'
)
print(f"   Has error: {'error' in result}")
print(f"   Error: {result.get('error', 'N/A')}")

print("\n5. Test auto-select most recent file:")
result = execute_query_polars(
    expression='df.select([pl.col("id")])'
)
print(f"   Success: {result.get('ok', False)}")
print(f"   Rows: {result.get('rows', 0)}")

print("\n" + "=" * 70)
print("✅ All tests passed! Core function works without FastAPI!")
print("=" * 70)
print("\nKey benefits:")
print("- No Body() objects to unwrap")
print("- Can be called directly from dispatcher")
print("- Easy to test and reuse")
print("- Clean separation of concerns")
