"""Test automatic NG link generation in query results."""
import sys
sys.path.insert(0, 'src')

import polars as pl
from neurogabber.backend.main import execute_query_polars, DATA_MEMORY, CURRENT_STATE
from neurogabber.backend.tools.neuroglancer_state import NeuroglancerState

# Reset state
CURRENT_STATE = NeuroglancerState()

# Create test dataframe with spatial columns
df = pl.DataFrame({
    'cluster_id': ['A', 'B', 'C'],
    'x': [100.5, 200.3, 300.8],
    'y': [150.2, 250.6, 350.1],
    'z': [50.9, 75.4, 100.2],
    'cell_count': [10, 20, 15]
})

# Convert to CSV bytes
csv_bytes = df.write_csv().encode('utf-8')

# Add to data memory
file_id = DATA_MEMORY.add_file("test.csv", csv_bytes)['file_id']
print(f"Added file: {file_id}")

# Test 1: Query with spatial columns should generate links
print("\n=== Test 1: Query with x,y,z columns ===")
result = execute_query_polars(
    file_id=file_id,
    expression="df.select(['cluster_id', 'x', 'y', 'z', 'cell_count'])"
)

print(f"Columns: {result.get('columns')}")
print(f"Rows: {result.get('rows')}")
print(f"Has ng_views: {'ng_views' in result}")
if 'ng_views' in result:
    print(f"Spatial columns detected: {result.get('spatial_columns')}")
    print(f"Number of views: {len(result['ng_views'])}")
    print(f"First view: row_index={result['ng_views'][0]['row_index']}, url={result['ng_views'][0]['url'][:100]}...")

# Test 2: Query with centroid columns
print("\n=== Test 2: Query with centroid_x,y,z columns ===")
df2 = pl.DataFrame({
    'cell_id': [1, 2, 3],
    'centroid_x': [100, 200, 300],
    'centroid_y': [150, 250, 350],
    'centroid_z': [50, 75, 100]
})
csv_bytes2 = df2.write_csv().encode('utf-8')
file_id2 = DATA_MEMORY.add_file("test2.csv", csv_bytes2)['file_id']

result2 = execute_query_polars(
    file_id=file_id2,
    expression="df"
)

print(f"Has ng_views: {'ng_views' in result2}")
if 'ng_views' in result2:
    print(f"Spatial columns detected: {result2.get('spatial_columns')}")
    print(f"Number of views: {len(result2['ng_views'])}")

# Test 3: Query without spatial columns
print("\n=== Test 3: Query without spatial columns ===")
df3 = pl.DataFrame({
    'cluster_id': ['A', 'B', 'C'],
    'cell_count': [10, 20, 15]
})
csv_bytes3 = df3.write_csv().encode('utf-8')
file_id3 = DATA_MEMORY.add_file("test3.csv", csv_bytes3)['file_id']

result3 = execute_query_polars(
    file_id=file_id3,
    expression="df"
)

print(f"Has ng_views: {'ng_views' in result3}")
print(f"Columns: {result3.get('columns')}")

print("\n✅ All tests completed")
