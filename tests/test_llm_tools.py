import re

from neuroglancer_chat.backend.adapters import llm


def test_tool_names_are_underscored_and_valid():
    pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
    names = [t["function"]["name"] for t in llm.TOOLS]
    # Ensure all names match the allowed pattern
    for name in names:
        assert pattern.match(name), f"Invalid tool name: {name}"
    # Ensure expected set of tools exists
    assert set(names) == {
        "ng_set_view",
        "ng_set_lut",
        "ng_annotations_add",
        "ng_add_layer",
        "ng_set_layer_visibility",
        "ng_set_viewer_settings",
        "data_plot_histogram",
        "data_ingest_csv_rois",
        "state_save",
        "state_load",
        "ng_state_summary",
        "ng_state_link",
        "data_info",
        "data_list_files",
        "data_ng_views_table",
        "data_ng_annotations_from_data",
        "data_preview",
        "data_describe",
        "data_list_summaries",
        "data_query_polars",
        "data_plot",
        "data_list_plots",
    }
