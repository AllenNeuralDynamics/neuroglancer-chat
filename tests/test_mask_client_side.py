"""Test that _mask_client_side doesn't double-wrap markdown links."""
from neuroglancer_chat.panel.panel_app import _mask_client_side

# Test 1: Raw URL should be masked
text1 = "Check this link: https://neuroglancer-demo.appspot.com#!{'layers':[]}"
result1 = _mask_client_side(text1)
print("Test 1 - Raw URL masking:")
print(f"  Input:  {text1}")
print(f"  Output: {result1}")
assert "[Updated Neuroglancer view](https://neuroglancer-demo.appspot.com" in result1
print("  ✓ Raw URL correctly masked\n")

# Test 2: Already-wrapped markdown link should NOT be re-masked
text2 = "Here's your data:\n\n| id | value | View |\n| 1 | 5.5 | [view](https://neuroglancer-demo.appspot.com#!view1) |\n"
result2 = _mask_client_side(text2)
print("Test 2 - Markdown link preservation:")
print(f"  Input:  {text2}")
print(f"  Output: {result2}")
assert "[view](https://neuroglancer-demo.appspot.com#!view1)" in result2
assert "Updated Neuroglancer view" not in result2
print("  ✓ Markdown links preserved\n")

# Test 3: Mixed content - raw URL and markdown link
text3 = """Raw URL: https://neuroglancer-demo.appspot.com#!raw
Already wrapped: [view](https://neuroglancer-demo.appspot.com#!wrapped)"""
result3 = _mask_client_side(text3)
print("Test 3 - Mixed content:")
print(f"  Input:  {text3}")
print(f"  Output: {result3}")
assert "[Updated Neuroglancer view](https://neuroglancer-demo.appspot.com#!raw)" in result3
assert "[view](https://neuroglancer-demo.appspot.com#!wrapped)" in result3
assert result3.count("Updated Neuroglancer view") == 1  # Only the raw URL
print("  ✓ Raw URL masked, markdown link preserved\n")

print("=" * 60)
print("✅ All _mask_client_side tests passed!")
print("=" * 60)
