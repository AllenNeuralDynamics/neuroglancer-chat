from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState, to_url, from_url


def test_clone_independence():
    s1 = NeuroglancerState()
    s1.add_layer("img", layer_type="image", source="precomputed://dummy")
    s2 = s1.clone()
    # mutate clone
    s2.set_view({"x": 1, "y": 2, "z": 3}, "fit", "xy")
    # original position should remain default
    assert s1.as_dict()["position"] == [0, 0, 0]
    assert s2.as_dict()["position"][:3] == [1, 2, 3]


def test_to_url_accepts_instance_round_trip():
    s = NeuroglancerState()
    s.add_layer("img", layer_type="image", source="precomputed://dummy")
    url = to_url(s)  # pass instance directly
    assert url.startswith("http") and "#!" in url
    parsed = from_url(url)
    # ensure the layer is present after round trip
    names = [L.get("name") for L in parsed.get("layers", [])]
    assert "img" in names
    # idempotent call with already serialized URL
    url2 = to_url(url)
    assert url == url2
