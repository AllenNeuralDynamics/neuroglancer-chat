"""Debug what the actual response looks like with ng_views."""
from neuroglancer_chat.panel.panel_app import _enhance_table_with_ng_views

# Simulate what the LLM might return
text = """Here are the query results:

| id | x | y | z | value |
|---:|---:|---:|---:|------:|
| 1 | 100 | 200 | 10 | 5.5 |
| 2 | 110 | 210 | 20 | 6.5 |
| 3 | 120 | 220 | 30 | 7.5 |

Total: 3 rows."""

ng_views = [
    {"row_index": 0, "url": "https://neuroglancer-demo.appspot.com#!view1"},
    {"row_index": 1, "url": "https://neuroglancer-demo.appspot.com#!view2"},
    {"row_index": 2, "url": "https://neuroglancer-demo.appspot.com#!view3"},
]

enhanced = _enhance_table_with_ng_views(text, ng_views)

print("ORIGINAL TEXT:")
print("=" * 60)
print(text)
print("\n" + "=" * 60)
print("\nENHANCED TEXT:")
print("=" * 60)
print(enhanced)
print("\n" + "=" * 60)

# Show character-by-character for debugging
print("\nFIRST TABLE LINE (enhanced):")
lines = enhanced.split("\n")
for i, line in enumerate(lines):
    if "|" in line:
        print(f"Line {i}: {repr(line)}")
        if i > 4:  # Just show first few table lines
            break
