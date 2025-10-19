"""Integration test for Phase 2: ng_views in backend response and frontend rendering."""
import re
from fastapi.testclient import TestClient
from neurogabber.backend.main import app

client = TestClient(app)


def test_ng_views_in_chat_response():
    """Test that ng_views are exposed in /agent/chat response."""
    # Upload a CSV with spatial columns
    content = b"id,x,y,z,value\n1,100,200,10,5.5\n2,110,210,20,6.5\n3,120,220,30,7.5\n"
    resp = client.post("/upload_file", files={"file": ("test.csv", content, "text/csv")})
    assert resp.status_code == 200
    fid = resp.json()["file"]["file_id"]
    
    # Make a chat request that triggers data_query_polars with spatial columns
    chat_resp = client.post("/agent/chat", json={
        "messages": [{"role": "user", "content": f"Query file {fid}: df.head(3)"}]
    })
    
    assert chat_resp.status_code == 200
    data = chat_resp.json()
    
    # Check that ng_views is present in response
    assert "ng_views" in data, f"ng_views missing from response. Keys: {data.keys()}"
    
    # If spatial columns were detected, ng_views should have data
    ng_views = data["ng_views"]
    if ng_views:
        assert isinstance(ng_views, list)
        assert len(ng_views) == 3  # 3 rows
        
        # Check structure of each view
        for view in ng_views:
            assert "row_index" in view
            assert "url" in view
            assert isinstance(view["row_index"], int)
            assert isinstance(view["url"], str)
            assert view["url"].startswith("https://")
            # Ensure URL is raw (not wrapped in markdown)
            assert not view["url"].startswith("[view]")
        
        print(f"✓ ng_views structure correct: {len(ng_views)} views")
        print(f"  Sample view: row_index={ng_views[0]['row_index']}, url starts with {ng_views[0]['url'][:50]}...")
    else:
        print("⚠ ng_views was None or empty (may be expected if no spatial columns)")
    
    # Check assistant message is present
    assert "choices" in data
    assert len(data["choices"]) > 0
    message = data["choices"][0]["message"]
    assert "content" in message
    
    print("✓ Chat response structure valid")


def test_frontend_table_enhancement():
    """Test the frontend's table enhancement function."""
    # Import the function
    from neurogabber.panel.panel_app import _enhance_table_with_ng_views
    
    # Sample markdown table
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
    
    # Check that View column was added
    assert "View |" in enhanced
    assert "[view](https://neuroglancer-demo.appspot.com#!view1)" in enhanced
    assert "[view](https://neuroglancer-demo.appspot.com#!view2)" in enhanced
    assert "[view](https://neuroglancer-demo.appspot.com#!view3)" in enhanced
    
    # Check all three views are present (more robust than counting pipes)
    view_links = [v["url"] for v in ng_views]
    for url in view_links:
        assert url in enhanced, f"Expected URL {url} in enhanced text"
    
    print("✓ Table enhancement adds View column correctly")
    print(f"  Enhanced table preview:")
    for line in enhanced.split("\n")[:10]:
        print(f"    {line}")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2 Integration Test: ng_views in Chat Response")
    print("=" * 60)
    
    print("\n1. Testing backend ng_views exposure...")
    test_ng_views_in_chat_response()
    
    print("\n2. Testing frontend table enhancement...")
    test_frontend_table_enhancement()
    
    print("\n" + "=" * 60)
    print("✅ Phase 2 Integration Tests Passed!")
    print("=" * 60)
