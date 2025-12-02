import polars as pl

# Create test dataframe similar to user's data
df = pl.DataFrame({
    'cluster_label': ['Pvalb_1', 'Pvalb_2', 'Sst_1', 'Pvalb_1', 'Sst_1'],
    'log_volume': [1.5, 2.3, 3.1, 1.8, 2.9]
})

print("Original DataFrame:")
print(df)
print()

# Test the expressions that failed
print("Test 1: df.groupby('cluster_label').agg(pl.max('log_volume'))")
try:
    result1 = df.groupby('cluster_label').agg(pl.max('log_volume'))
    print("Success!")
    print(result1)
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
print()

print("Test 2: df.groupby('cluster_label').agg([pl.max('log_volume')])")
try:
    result2 = df.groupby('cluster_label').agg([pl.max('log_volume')])
    print("Success!")
    print(result2)
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
print()

print("Test 3: df.group_by('cluster_label').agg(pl.max('log_volume'))")
try:
    result3 = df.group_by('cluster_label').agg(pl.max('log_volume'))
    print("Success!")
    print(result3)
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
print()

print("Test 4: df.group_by('cluster_label').agg(pl.col('log_volume').max())")
try:
    result4 = df.group_by('cluster_label').agg(pl.col('log_volume').max())
    print("Success!")
    print(result4)
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
