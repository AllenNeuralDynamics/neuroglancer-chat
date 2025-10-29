import json, os, uuid
from typing import Dict, Any, Iterable
from urllib.parse import quote, unquote


#NEURO_BASE = os.getenv("NEUROGLANCER_BASE", "https://neuroglancer.github.io")
NEURO_BASE = os.getenv("NEUROGLANCER_BASE", "https://neuroglancer-demo.appspot.com")


class NeuroglancerState:
    """Encapsulates a Neuroglancer state dict and provides mutation helpers.

    This class wraps the previously module-level functions. All existing
    top-level functions remain as thin delegating wrappers to preserve the
    external API relied upon by other modules and tests.

    Design notes:
    - The internal representation is a mutable ``dict`` stored in ``self.data``.
    - Methods mutate in-place and return ``self`` for optional chaining.
    - ``to_url`` & ``from_url`` provided as instance and ``@staticmethod`` to
      support both styles.
    - Idempotent behaviors (e.g. add_layer with an existing name) preserved.
    - Validation (layer type whitelist) retained.
    """

    def __init__(self, data: Dict | None = None):
        if data is None:
            data = {
                "dimensions": {"x": [1e-9, "m"], "y": [1e-9, "m"], "z": [1e-9, "m"]},
                "position": [0, 0, 0],
                "crossSectionScale": 1.0,
                "projectionScale": 1024,
                "layers": [],
                "layout": "xy",
            }
        self.data = data

    # --- Core mutation helpers -------------------------------------------------
    def set_view(self, center: Dict[str, float], zoom: Any, orientation: str | None):
        old_pos = self.data.get("position", [])
        if isinstance(old_pos, list) and len(old_pos) == 4:
            self.data["position"] = [center["x"], center["y"], center["z"], old_pos[3]]
        else:
            self.data["position"] = [center["x"], center["y"], center["z"]]

        if zoom == "fit":
            self.data["crossSectionScale"] = 1.0
        else:
            try:
                self.data["crossSectionScale"] = float(zoom)
            except Exception:  # pragma: no cover (defensive)
                pass
            if orientation:
                self.data["layout"] = orientation
        return self

    def set_lut(self, layer_name: str, vmin: float, vmax: float):
        for L in self.data.get("layers", []):
            if L.get("name") == layer_name:
                sc = L.setdefault("shaderControls", {})
                norm = sc.setdefault("normalized", {})
                norm["range"] = [vmin, vmax]
                break
        return self

    def add_layer(self, name: str, layer_type: str = "image", source: str | dict | None = None, **kwargs):
        if layer_type not in ALLOWED_LAYER_TYPES:
            raise ValueError(f"Unsupported layer_type '{layer_type}'. Allowed: {sorted(ALLOWED_LAYER_TYPES)}")
        if any(L.get("name") == name for L in self.data.get("layers", [])):
            return self  # idempotent
        
        # Special handling for annotation layers to match Neuroglancer's actual schema
        if layer_type == "annotation":
            if source is None:
                source = {"url": "local://annotations"}
            elif isinstance(source, str):
                source = {"url": source}
            
            # Get color from either annotationColor or annotation_color
            color = kwargs.pop("annotationColor", kwargs.pop("annotation_color", None))
            if not color:
                color = "#cecd11"  # Default yellow
            
            # Annotation layers need these fields at layer level (not in source)
            layer = {
                "type": layer_type,
                "source": source,
                "tool": kwargs.pop("tool", "annotatePoint"),
                "tab": kwargs.pop("tab", "annotations"),
                "annotationColor": color,
                "annotations": [],  # annotations array at layer level
                "name": name,
            }
        else:
            # For image/segmentation layers, use string source
            if source is None:
                source = "precomputed://example"
            
            layer = {
                "type": layer_type,
                "name": name,
                "source": source,
                "visible": kwargs.pop("visible", True),
            }
        
        for k, v in kwargs.items():
            layer[k] = v
        self.data.setdefault("layers", []).append(layer)
        return self

    def set_layer_visibility(self, name: str, visible: bool):
        for L in self.data.get("layers", []):
            if L.get("name") == name:
                L["visible"] = bool(visible)
                break
        return self

    def add_annotations(self, layer: str, items: Iterable[Dict]):
        """Add annotation items to an annotation layer.
        
        Follows Neuroglancer's actual schema:
        - annotations array is at layer level (not in source)
        - each item must have 'type' field ('point', 'box', 'ellipsoid', etc.)
        """
        ann = next((L for L in self.data.get("layers", []) if L.get("type") == "annotation" and L.get("name") == layer), None)
        if not ann:
            # Create layer if it doesn't exist
            self.add_layer(layer, "annotation")
            ann = next((L for L in self.data.get("layers", []) if L.get("type") == "annotation" and L.get("name") == layer))
        
        # Ensure annotations array exists at layer level
        ann.setdefault("annotations", []).extend(items)
        return self

    # --- Serialization helpers -------------------------------------------------
    def to_url(self) -> str:
        return to_url(self.data)

    @staticmethod
    def from_url(url_or_fragment: str) -> "NeuroglancerState":
        return NeuroglancerState(from_url(url_or_fragment))

    # Convenience for tests / external callers wanting the raw dict
    def as_dict(self) -> Dict:
        return self.data

    # --- Utility helpers ------------------------------------------------------
    def clone(self) -> "NeuroglancerState":
        """Return a deep copy of this NeuroglancerState.

        Uses json round-trip for a deterministic deep copy without relying on
        potentially unsafe references in nested dict/list structures. Faster
        than serializing to a full Neuroglancer URL then parsing.
        """
        # json round-trip is adequate given the state is pure JSON-compatible primitives
        import json as _json
        return NeuroglancerState(_json.loads(_json.dumps(self.data)))


ALLOWED_LAYER_TYPES = {"image", "segmentation", "annotation"}


def to_url(state) -> str:
    """Serialize a Neuroglancer state to a shareable URL.

    Accepts:
      - a dict (canonical case)
      - a full Neuroglancer URL (idempotent: returns normalized form)
      - a fragment starting with '#', '#!' or raw percent-encoded JSON
      - a raw JSON string

    This makes accidental double-calls (e.g. ``to_url(to_url(state))``) safe by
    detecting string inputs and parsing them back to a dict before serializing
    again. Deterministic JSON (sorted keys, compact separators) ensures stable
    tests and reproducible links.
    """
    # Allow callers to pass a NeuroglancerState instance directly.
    if isinstance(state, NeuroglancerState):  # new: accept object instance
        state = state.as_dict()
    # If caller passed a string, attempt to parse it to a dict first.
    if isinstance(state, str):
        try:
            state = from_url(state)  # re-use robust parser above
        except Exception as e:  # pragma: no cover (defensive)
            raise ValueError(f"to_url() received a string that is not a valid Neuroglancer state: {e}")

    if not isinstance(state, dict):  # pragma: no cover (defensive)
        raise TypeError("to_url() expects a dict or serializable state string")

    # CRITICAL: Do NOT use sort_keys=True here as it will reorder the dimensions
    # (e.g., x,y,z,t -> t,x,y,z) which breaks the position array mapping!
    # Python 3.7+ preserves dict insertion order, so we maintain the original dimension order.
    state_str = json.dumps(state, separators=(",", ":"))
    encoded = quote(state_str, safe="")
    # Neuroglancer canonical form uses '#!' before the JSON; include it.
    return f"{NEURO_BASE}#!{encoded}"


def from_url(url_or_fragment: str) -> Dict:
    """Parse a Neuroglancer URL (or just its hash fragment) into a state dict.

    Accepts any of:
    - Full URL like https://host/#!%7B...%7D
    - Full URL like https://host/#%7B...%7D
    - Just the fragment starting with '#', '#!' or the percent-encoded JSON itself
    - A raw JSON string (for robustness)
    """
    s = url_or_fragment.strip()
    # Extract the fragment if a full URL was provided
    if '#' in s:
        s = s.split('#', 1)[1]
    # Drop the optional leading '!'
    if s.startswith('!'):
        s = s[1:]
    # If this looks like percent-encoded JSON, unquote it
    try:
        decoded = unquote(s)
        # If unquoting didn't change it and it's already JSON, keep as-is
        candidate = decoded if decoded else s
        return json.loads(candidate)
    except Exception:
        # Last resort: maybe it's already a JSON string without quoting
        return json.loads(s)