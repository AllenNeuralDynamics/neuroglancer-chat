"""Debug table enhancement."""
from neuroglancer_chat.panel.panel_app import _enhance_table_with_ng_views

text = """Here are the results:

| id | x | y | z | value |
| --- | --- | --- | --- | --- |
| 1 | 100 | 200 | 10 | 5.5 |
| 2 | 110 | 210 | 20 | 6.5 |
| 3 | 120 | 220 | 30 | 7.5 |

Analysis complete."""

ng_views = [
    {"row_index": 0, "url": "https://neuroglancer-demo.appspot.com#!view1"},
    {"row_index": 1, "url": "https://neuroglancer-demo.appspot.com#!view2"},
    {"row_index": 2, "url": "https://neuroglancer-demo.appspot.com#!view3"},
]

enhanced = _enhance_table_with_ng_views(text, ng_views)

print("Enhanced text:")
print(enhanced)
print("\n" + "=" * 60)
print(f"Count of ' View |': {enhanced.count(' View |')}")
print(f"view1 present: {'view1' in enhanced}")
print(f"view2 present: {'view2' in enhanced}")
print(f"view3 present: {'view3' in enhanced}")
