"""Shared tool classification constants.

Centralizes definition of which tools mutate the Neuroglancer state so that
frontend, backend chat loop, and tests do not drift.
"""

from __future__ import annotations

MUTATING_TOOLS: set[str] = {
    "ng_set_view",
    "ng_set_lut",
    "ng_annotations_add",
    "ng_add_layer",
    "ng_set_layer_visibility",
    "ng_set_viewer_settings",
    "state_load",            # replaces entire state
    "data_ingest_csv_rois",  # may add an annotation layer
    "data_ng_views_table",   # generates multiple view mutations
    "data_ng_annotations_from_data",  # adds annotations from dataframe rows
}


def is_mutating_tool(name: str) -> bool:
    return name in MUTATING_TOOLS
