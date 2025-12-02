from typing import Any, Dict

import jsonschema
from neuroglancer_chat.backend.adapters.llm import TOOLS


def _walk_schema(schema: Dict[str, Any]):
    """Yield all nested schemas (DFS)."""
    yield schema
    if isinstance(schema, dict):
        for key in ("properties", "patternProperties"):
            if key in schema and isinstance(schema[key], dict):
                for sub in schema[key].values():
                    yield from _walk_schema(sub)
        # handle array items
        if "items" in schema and isinstance(schema["items"], (dict, list)):
            if isinstance(schema["items"], dict):
                yield from _walk_schema(schema["items"])
            else:
                for sub in schema["items"]:
                    yield from _walk_schema(sub)
        # handle combinators
        for key in ("allOf", "anyOf", "oneOf", "not"):
            if key in schema:
                subs = schema[key]
                if isinstance(subs, list):
                    for sub in subs:
                        yield from _walk_schema(sub)
                elif isinstance(subs, dict):
                    yield from _walk_schema(subs)


def test_tool_param_schemas_are_valid_jsonschema():
    for tool in TOOLS:
        params = tool["function"].get("parameters")
        assert params and isinstance(params, dict)
        # should be a valid JSON Schema Draft 7
        jsonschema.Draft7Validator.check_schema(params)


def test_arrays_define_items_schemas():
    for tool in TOOLS:
        params = tool["function"].get("parameters", {})
        for node in _walk_schema(params):
            if isinstance(node, dict) and node.get("type") == "array":
                assert "items" in node, "Array schema missing 'items' definition"
