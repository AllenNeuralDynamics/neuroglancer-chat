from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState


def test_set_lut_creates_normalized_range():
    s = NeuroglancerState({"layers": [
        {"type": "image", "name": "vol", "source": "precomputed://dummy"}
    ]})
    s.set_lut('vol', 2, 9)
    state = s.as_dict()
    layer = state['layers'][0]
    assert 'shaderControls' in layer
    assert 'normalized' in layer['shaderControls']
    assert layer['shaderControls']['normalized']['range'] == [2, 9]


def test_set_lut_updates_existing():
    s = NeuroglancerState({"layers": [
        {"type": "image", "name": "vol", "source": "precomputed://dummy",
         "shaderControls": {"normalized": {"range": [0,1], "otherKey": 5}}}
    ]})
    s.set_lut('vol', 10, 20)
    state = s.as_dict()
    rng = state['layers'][0]['shaderControls']['normalized']['range']
    assert rng == [10, 20]
    # Ensure unrelated keys preserved
    assert state['layers'][0]['shaderControls']['normalized']['otherKey'] == 5