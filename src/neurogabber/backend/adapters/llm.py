import os, json
from typing import List, Dict
from openai import OpenAI

_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # Configurable via env var
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")  # Configurable via env var

client = None
if _API_KEY:
  client = OpenAI(api_key=_API_KEY)

SYSTEM_PROMPT = """
You are Neuroglancer Chat, a helpful assistant for navigating the Neuroglancer user interface.

⚠️ CRITICAL: TAKE ACTION FIRST, EXPLAIN LATER. Use tools immediately when the user asks about data.

Decision rules:
- DEFAULT TO ACTION: When in doubt, call a tool. Don't ask permission or explain first.
- Data questions = IMMEDIATE tool call. Examples: "what are the unique values?", "how many rows?", "show me X" → call the tool NOW in your first response.
- If the user only wants information answer directly from the provided 'Current viewer state summary' (no tools).
- If the user wants to modify the view/viewer (camera, LUTs, annotations, layers) call the corresponding tool(s).
- If unsure of layer names or ranges, call ng_state_summary first (detail='standard' unless user requests otherwise).
- After performing modifications, if the user requests a link or updated view, call ng_state_link (NOT state_save) to return a masked markdown hyperlink. Only call state_save when explicit persistence is requested (e.g. 'save', 'persist', 'store').
- Do not paste raw Neuroglancer URLs directly; always rely on ng_state_link for sharing the current view.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 POLARS SYNTAX - CRITICAL DIFFERENCES FROM PANDAS 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ THIS IS POLARS, NOT PANDAS! Key differences:

❌ WRONG (pandas):          ✅ CORRECT (Polars):
   df.groupby('col')            df.group_by('col')         [underscore!]
   .sort(reverse=True)          .sort(descending=True)     [different param!]
   df['col'].max()              df.select(pl.max('col'))   [use pl functions!]

Common ERROR patterns to AVOID:
• df.groupby() → TypeError ❌  USE: df.group_by() ✓
• sort(reverse=True) → TypeError ❌  USE: sort(descending=True) ✓
• Accessing columns with brackets in aggregations ❌  USE: pl.col() ✓

Dataframe rules - ACTION REQUIRED:
- ANY question about CSV/dataframe content = IMMEDIATE tool call. Do NOT respond with text first.
- When the user mentions "data", "dataframe", "file", or "csv" without specifying which file, ALWAYS use the most recent file (shown in Data context).
- Questions like "what are the unique values in X?" or "how many Y?" or "show me Z" → call data_query_polars IMMEDIATELY.
- For simple operations, use specific tools (data_preview, data_describe).
- For complex queries (multiple filters, aggregations, computed columns, sorting), use data_query_polars with a Polars expression.
- In data_query_polars: use 'df' for the dataframe and 'pl' for Polars functions. All standard Polars operations are supported.
- Common Polars patterns:
  * Grouping: df.group_by('col').agg(pl.col('value').max())
  * Filtering: df.filter(pl.col('x') > 5)
  * Selecting: df.select(['col1', 'col2'])
  * Sorting: df.sort('col') or df.sort('col', descending=True)
  * Unique values: df.select(pl.col('col').unique())
  * Sampling: df.sample(n=10) or df.sample(n=10, seed=42) for reproducibility
- IMPORTANT: When aggregating or sampling data, ALWAYS include spatial columns (x,y,z or centroid_x,centroid_y,centroid_z) if they exist in the source data. This enables automatic Neuroglancer view links for each row.
  * Example: df.group_by('cluster_id').agg(pl.first('x'), pl.first('y'), pl.first('z'), pl.first('cell_id'))
  * When using .sample(), the spatial columns are automatically included.
- If you want to reuse a query result, use save_as parameter to store it as a summary table, then reference it with summary_id in subsequent queries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
� QUERY RESULT CHAINING - CRITICAL FOR MULTI-STEP WORKFLOWS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ IMPORTANT: All data_query_polars results are AUTOMATICALLY SAVED!
• Every query returns a summary_id in the response
• You can use that summary_id for follow-up operations
• Query results contain the TRANSFORMED data (filtered/aggregated/etc.)
• SHORTCUT: Use summary_id="last" OR omit both file_id and summary_id to use the most recent query

Example: "Get top cell per cluster and annotate them"

✅ CORRECT Option 1 (Use explicit summary_id):
   Step 1: data_query_polars(
       file_id="abc123",
       expression="df.group_by('cluster_label').agg(...)"
   )
   → Response: {"summary_id": "query_789", "rows": 20, ...}
   
   Step 2: data_ng_annotations_from_data(
       summary_id="query_789",  # ← Explicit summary_id
       layer_name="Clusters",
       ...
   )

✅ CORRECT Option 2 (Use "last" shorthand):
   Step 1: data_query_polars(expression="...")
   Step 2: data_ng_annotations_from_data(
       summary_id="last",  # ← Automatic reference to most recent query
       layer_name="Clusters",
       ...
   )

✅ CORRECT Option 3 (Omit both - auto-uses last query):
   Step 1: data_query_polars(expression="...")
   Step 2: data_ng_annotations_from_data(
       # No file_id or summary_id → automatically uses last query result
       layer_name="Clusters",
       ...
   )

❌ WRONG (Using original file_id):
   Step 1: data_query_polars(file_id="abc123", expression="...")
   Step 2: data_ng_annotations_from_data(file_id="abc123", ...)  # ← WRONG!
   → Creates annotations from ALL cells in original file, not the query result! ✗

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
�📚 WORKFLOW RECIPES - Common Task Patterns
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Recipe 1: ADD ANNOTATION POINTS FROM FILTERED/AGGREGATED DATA
Task: "Add annotation points for the top cell in each cluster"

✅ OPTION A (Recommended - Two-step with auto-saved summary_id):
   Step 1: data_query_polars(
       file_id="...",
       expression="df.group_by('cluster_label').agg(pl.first('centroid_x'), pl.first('centroid_y'), pl.first('centroid_z'), pl.max('log_volume'))"
   )
   → Note the summary_id in the response!
   
   Step 2: data_ng_annotations_from_data(
       summary_id="<use_summary_id_from_step_1>",  # ← Critical!
       layer_name="Clusters",
       center_columns=["centroid_x", "centroid_y", "centroid_z"],
       color="#00ff00"
   )

✅ OPTION B (Single-call with filter_expression):
   data_ng_annotations_from_data(
       file_id="...",
       filter_expression="df.group_by('cluster_label').agg(pl.first('centroid_x'), pl.first('centroid_y'), pl.first('centroid_z'), pl.max('log_volume'))",
       layer_name="Clusters",
       center_columns=["centroid_x", "centroid_y", "centroid_z"],
       color="#00ff00"
   )

❌ WRONG (Don't use original file_id after querying):
   data_query_polars(file_id="...", expression="...")
   data_ng_annotations_from_data(file_id="...", ...)  # Uses wrong data!

Recipe 2: GET TOP N BY METRIC WITH SPATIAL DATA
Task: "Show me top 5 cells by volume in each cluster"
✅ Use: data_query_polars with FULL aggregation including spatial columns
   Expression: "df.group_by('cluster_id').agg(
                  pl.max('volume').alias('max_volume'),
                  pl.first('centroid_x'),
                  pl.first('centroid_y'), 
                  pl.first('centroid_z'),
                  pl.first('cell_id')
                ).sort('max_volume', descending=True).head(5)"

Recipe 3: INTERACTIVE VIEW TABLE WITH LINKS
Task: "Create clickable links to view top cells"
✅ Use: data_ng_views_table
   - Automatically generates Neuroglancer links
   - Returns table with click-to-view functionality
   - First view is auto-loaded
- ⚠️ CRITICAL: When you receive tool results from data_query_polars, DO NOT format, summarize, or display the data in ANY way.
  * The tool returns "data" in a structured format that goes DIRECTLY to the frontend
  * The frontend automatically renders an interactive table widget with the expression displayed above it
  * Your ONLY job after a data_query_polars tool call:
    - Provide a brief summary of context (optional): "Here are the top 20 unique cluster_id values."
    - That's it! STOP. The frontend will show the expression and table automatically.
  * ❌ NEVER show the Polars expression in a code block (frontend handles this)
  * ❌ NEVER write things like: "cell_id: 91500 | volume_um: 1530.6 | ..."
  * ❌ NEVER create markdown tables with | ... |
  * ❌ NEVER list individual data values
  * ✅ CORRECT example: "Here are the top 20 unique values in cluster_id (as requested by the tool)."
  * ✅ Keep it brief - the expression and table appear automatically!
- If the result includes "ng_views" field, you can add: "(View links available)" but don't construct URLs or links.

Plotting rules - ACTION REQUIRED:
- ⚠️ CRITICAL: ANY request with "plot", "graph", "visualize", "chart", "scatter", "scatterplot", "scatter plot", "lineplot", "line plot", "barplot", "bar plot", "heatmap" → call data_plot immediately (NOT data_query_polars).
- Use data_plot for ALL visualization requests, even with sampling or filtering.
- If data needs transformation (sampling, filtering, aggregation), provide `expression` parameter with Polars query.
- Example 1: "sample 20 cells and scatterplot log_volume vs elongation"
  → Call data_plot with: expression='df.sample(20)', plot_type='scatter', x='log_volume', y='elongation'
- Example 2: "plot mean log_volume for cluster labels"
  → Call data_plot with: expression='df.group_by("cluster_label").agg(pl.mean("log_volume"))', plot_type='bar', x='cluster_label', y='log_volume'
  ⚠️ CRITICAL: Must use group_by().agg() to aggregate - don't just select or filter!
- Example 3: "plot max log_volume by cluster_label"
  → Call data_plot with: expression='df.group_by("cluster_label").agg(pl.max("log_volume"))', plot_type='bar', x='cluster_label', y='log_volume'
  ⚠️ The column name in agg result is STILL the original column name (log_volume), NOT max_log_volume
- Example 4: "plot mean log_volume for cluster labels with elongation > 0.5"
  → Call data_plot with: expression='df.filter(pl.col("elongation") > 0.5).group_by("cluster_label").agg(pl.mean("log_volume"))', plot_type='bar', x='cluster_label', y='log_volume'
- ⚠️ NOTE: Do NOT use 'by' parameter when data is already aggregated by x-axis column
- The 'by' parameter is for creating multiple series (e.g., scatter plot colored by category), NOT for bar plot grouping
- For bar plots showing aggregated values: ALWAYS use group_by().agg() in expression, set x to category column, y to metric column, NO 'by' parameter
- For scatter plots from raw data without transformation, omit expression.
- Common plot types: scatter (x/y points), line (trends), bar (categorical comparisons), heatmap (matrix).
- ⚠️ CRITICAL: After data_plot returns, DO NOT describe the plot or summarize data. The frontend renders it automatically.
  * Just say: "Here's your plot." or similar single sentence.
  * The interactive plot appears automatically in the Panel UI.
- ALWAYS include spatial columns in expressions when aggregating data (x, y, z or centroid_x, centroid_y, centroid_z) to enable future Neuroglancer click-to-view features.

Conversation context awareness:
- If you just returned data/results in the previous response, the user's next question likely refers to that data.
- When the user asks a follow-up question about filtering, counting, or analyzing data you just showed, they mean the data from your previous response.
- Before making a new query, check if you can answer from the data you just returned.

Keep answers concise. Provide brief rationale AFTER tool results, not before. Avoid redundant summaries."""

# Define available tools (schemas must match your Pydantic models)
TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "ng_set_view",
      "description": "Set camera center/zoom/orientation",
      "parameters": {
        "type": "object",
        "properties": {
          "center": {"type":"object","properties":{"x":{"type":"number"},"y":{"type":"number"},"z":{"type":"number"}},"required":["x","y","z"]},
          "zoom": {"oneOf":[{"type":"number"},{"type":"string","enum":["fit"]}]},
          "orientation": {"type":"string","enum":["xy","yz","xz","3d"]}
        },
        "required": ["center"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "ng_add_layer",
      "description": "Add a new Neuroglancer layer (image, segmentation, or annotation). Idempotent if name exists. For annotation layers, specify annotation_color as a hex color (e.g., '#00ff00' for green, '#ff0000' for red, '#0000ff' for blue).",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "layer_type": {"type": "string", "enum": ["image","segmentation","annotation"], "default": "image"},
          "source": {"description": "Layer source spec (string or object, passed through)", "oneOf": [
            {"type": "string"},
            {"type": "object"},
            {"type": "null"}
          ]},
          "visible": {"type": "boolean", "default": True},
          "annotation_color": {"type": "string", "description": "Hex color for annotation layer (e.g., '#00ff00' for green, '#ff0000' for red). Only used for annotation layers."}
        },
        "required": ["name"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "ng_set_layer_visibility",
      "description": "Toggle visibility of an existing layer (adds 'visible' key if missing).",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "visible": {"type": "boolean"}
        },
        "required": ["name","visible"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "ng_set_viewer_settings",
      "description": "Set viewer-level display settings (scale bar, axis lines, default annotations, layout mode). All parameters optional - only specified settings will be updated.",
      "parameters": {
        "type": "object",
        "properties": {
          "showScaleBar": {"type": "boolean", "description": "Show/hide scale bar overlay"},
          "showDefaultAnnotations": {"type": "boolean", "description": "Show/hide default annotations"},
          "showAxisLines": {"type": "boolean", "description": "Show/hide axis lines in viewer"},
          "layout": {"type": "string", "enum": ["xy", "xz", "yz", "3d", "4panel"], "description": "Viewer layout mode"}
        }
      }
    }
  },
  {
    "type":"function",
    "function": {
      "name":"ng_set_lut",
      "description":"Set value range for an image layer",
      "parameters": {
        "type":"object",
        "properties": {"layer":{"type":"string"},"vmin":{"type":"number"},"vmax":{"type":"number"}},
        "required":["layer","vmin","vmax"]
      }
    }
  },
  {
    "type":"function",
    "function": {
      "name":"ng_annotations_add",
      "description":"Add annotations to a layer",
      "parameters": {
        "type": "object",
        "properties": {
          "layer": {"type": "string"},
          "items": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "id": {"type": "string"},
                "type": {"type": "string", "enum": ["point", "box", "ellipsoid"]},
                "center": {
                  "type": "object",
                  "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"}
                  },
                  "required": ["x", "y", "z"]
                },
                "size": {
                  "type": "object",
                  "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"}
                  }
                }
              },
              "required": ["type", "center"]
            }
          }
        },
        "required": ["layer", "items"]
      }
    }
  },
  {
    "type":"function",
    "function": {
      "name":"data_plot_histogram",
      "description":"Compute intensity histogram from layer/roi",
      "parameters": {"type":"object","properties": {"layer":{"type":"string"},"roi":{"type":"object"}},"required":["layer"]}
    }
  },
  {
    "type":"function",
    "function": {
      "name":"data_ingest_csv_rois",
      "description":"Load CSV of ROIs and build canonical table",
      "parameters": {"type":"object","properties": {"file_id":{"type":"string"}},"required":["file_id"]}
    }
  },
  {"type":"function","function": {"name":"state_save","description":"Save and return NG state URL","parameters":{"type":"object","properties":{}}}},
  {"type":"function","function": {"name":"state_load","description":"Load state from a Neuroglancer URL or fragment","parameters":{"type":"object","properties":{"link":{"type":"string"}},"required":["link"]}}},
  {"type":"function","function": {"name":"ng_state_summary","description":"Get structured summary of current Neuroglancer state for reasoning. Use before modifications if unsure of layer names or ranges.","parameters":{"type":"object","properties":{"detail":{"type":"string","enum":["minimal","standard","full"],"default":"standard"}}}}},
  {"type":"function","function": {"name":"ng_state_link","description":"Return current state Neuroglancer link plus masked markdown hyperlink (use after modifications when user requests link).","parameters":{"type":"object","properties":{}}}}
]

# Data tools appended
DATA_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "data_list_files",
      "description": "List uploaded CSV files with metadata (ids, columns).",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_ng_views_table",
      "description": "Generate multiple Neuroglancer view links from a dataframe (e.g., top N by a metric) returning a table of id + metrics + links. Mutates state to first view.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "Source file id (provide either file_id OR summary_id)"},
          "summary_id": {"type": "string", "description": "Existing summary/derived table id (mutually exclusive with file_id)"},
          "sort_by": {"type": "string"},
          "descending": {"type": "boolean", "default": True},
          "top_n": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
          "id_column": {"type": "string", "default": "cell_id"},
          "center_columns": {"type": "array", "items": {"type": "string"}, "default": ["x","y","z"]},
          "include_columns": {"type": "array", "items": {"type": "string"}},
          "lut": {"type": "object", "properties": {"layer": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"}}},
          "annotations": {"type": "boolean", "default": False},
          "link_label_column": {"type": "string"}
        },
        # Note: cannot express mutual exclusivity without oneOf (disallowed by OpenAI);
        # model should infer to supply only one of file_id or summary_id.
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_ng_annotations_from_data",
      "description": "Create Neuroglancer annotation points/boxes/ellipsoids directly from dataframe rows. Each row becomes one annotation at the specified spatial coordinates. IMPORTANT: If you just called data_query_polars, use the returned summary_id (NOT the original file_id) to annotate the QUERY RESULT. Optionally use filter_expression to transform data inline.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "Source file id. Use this ONLY if annotating the full original dataset. If you just ran a query, use summary_id instead!"},
          "summary_id": {"type": "string", "description": "ID of saved query result (returned by data_query_polars). Use 'last' to reference the most recent query. CRITICAL: Use this when creating annotations from filtered/aggregated data, not the original file_id!"},
          "layer_name": {"type": "string", "description": "Name of annotation layer to create/add to"},
          "annotation_type": {"type": "string", "enum": ["point", "box", "ellipsoid"], "default": "point"},
          "center_columns": {"type": "array", "items": {"type": "string"}, "default": ["x", "y", "z"], "description": "Column names for x,y,z coordinates (e.g., ['centroid_x', 'centroid_y', 'centroid_z'])"},
          "size_columns": {"type": "array", "items": {"type": "string"}, "description": "For box/ellipsoid: column names for width,height,depth dimensions"},
          "id_column": {"type": "string", "description": "Optional: column to use for annotation IDs (e.g., 'cell_id')"},
          "color": {"type": "string", "description": "Hex color for layer (e.g., '#00ff00' for green, '#ff0000' for red)"},
          "filter_expression": {"type": "string", "description": "Optional Polars expression to filter/transform data before creating annotations. Use 'df' for dataframe. Example: 'df.filter(pl.col(\"cluster_id\") == 3).head(10)' or 'df.group_by(\"cluster_label\").agg(pl.first(\"centroid_x\"), pl.first(\"centroid_y\"), pl.first(\"centroid_z\"), pl.max(\"log_volume\"))'"},
          "limit": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 5000, "description": "Maximum number of annotations to create"}
        },
        "required": ["layer_name"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_info",
      "description": "Return dataframe metadata (rows, cols, columns, dtypes, head sample). Call before asking questions about the dataset.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string"},
          "sample_rows": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20}
        },
        "required": ["file_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_preview",
      "description": "Preview first N rows of a file.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string"},
          "n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100}
        },
        "required": ["file_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_describe",
      "description": "Compute numeric summary statistics for a file.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string"}
        },
        "required": ["file_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_list_summaries",
      "description": "List previously created summary / derived tables.",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_query_polars",
      "description": "Execute Polars expression on a dataframe. Supports any Polars operations (filter, select, group_by, agg, with_columns, sort, etc.). Use this for complex queries that would require multiple tool calls otherwise. Returns resulting dataframe.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "ID of uploaded file to query. Provide file_id for original uploaded files (most common case)."},
          "summary_id": {"type": "string", "description": "ID of a previously saved query result. Only use if you saved a result with save_as in a previous call. Do not provide both file_id and summary_id."},
          "expression": {
            "type": "string",
            "description": "Polars expression to execute. Use 'df' to reference the dataframe and 'pl' for Polars functions. For aggregations, use df.select([pl.max('col')]) not df['col'].max(). Examples: 'df.filter(pl.col(\"age\") > 30).select([\"id\", \"name\"])' or 'df.select([pl.max(\"score\"), pl.mean(\"age\")])'"
          },
          "save_as": {"type": "string", "description": "Optional: save result as a named summary table for reuse in subsequent queries"},
          "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000, "description": "Maximum rows to return"}
        },
        "required": ["expression"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_plot",
      "description": "Generate interactive plot (scatter/line/bar/heatmap) from dataframe. Can apply Polars expression first to transform data. Returns embeddable plot HTML. Spatial columns (x,y,z) are automatically preserved for future Neuroglancer click-to-view features.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "Source file ID (provide file_id OR summary_id)"},
          "summary_id": {"type": "string", "description": "Source summary table ID (mutually exclusive with file_id)"},
          "plot_type": {
            "type": "string",
            "enum": ["scatter", "line", "bar", "heatmap"],
            "description": "Type of plot: scatter (x/y points), line (trends), bar (categorical comparisons), heatmap (matrix)"
          },
          "x": {"type": "string", "description": "X-axis column name (required)"},
          "y": {"type": "string", "description": "Y-axis column name (required)"},
          "by": {"type": "string", "description": "Grouping column - creates multiple colored series in scatter/line plots. For bar plots, do NOT use 'by' when data is already aggregated - just set x to the category column and y to the metric."},
          "size": {"type": "string", "description": "Column for point size (scatter only)"},
          "color": {"type": "string", "description": "Column for point color (scatter only)"},
          "stacked": {"type": "boolean", "default": False, "description": "Stack bars side-by-side (bar plot only, default is grouped/side-by-side bars)"},
          "title": {"type": "string", "description": "Plot title"},
          "expression": {
            "type": "string",
            "description": "Optional Polars expression to transform data before plotting. IMPORTANT: Always include spatial columns (x,y,z or centroid_x,centroid_y,centroid_z) in aggregations. Example: 'df.filter(pl.col(\"elongation\") > 0.5).group_by(\"cluster_id\").agg(pl.mean(\"log_volume\"), pl.first(\"x\"), pl.first(\"y\"), pl.first(\"z\"))'"
          },
          "save_plot": {"type": "boolean", "default": True, "description": "Store plot in workspace"},
          "interactive_override": {"type": "boolean", "description": "Force interactive on/off (default: auto, interactive if ≤200 points)"}
        },
        "required": ["plot_type", "x", "y"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_list_plots",
      "description": "List all generated plots in the workspace with metadata.",
      "parameters": {"type": "object", "properties": {}}
    }
  },
]

TOOLS = TOOLS + DATA_TOOLS


def run_chat(messages: List[Dict]) -> Dict:
  if client is None:
    # Fallback mock response for test environments without API key.
    # Return structure mimicking OpenAI response with no tool calls so logic can proceed.
    return {
      "choices": [{"index": 0, "message": {"role": "assistant", "content": "(LLM disabled: no OPENAI_API_KEY set)"}}],
      "usage": {}
    }
  
  # Enable prompt caching by adding cache_control to system messages
  # This tells OpenAI to cache the static prefix (system prompts + tools)
  cached_messages = []
  for i, msg in enumerate(messages):
    msg_copy = msg.copy()
    # Mark the last system message for caching (must be >1024 tokens typically)
    if msg.get("role") == "system" and i < len(messages) - 1 and messages[i + 1].get("role") != "system":
      # This is the last system message before user messages
      msg_copy["cache_control"] = {"type": "ephemeral"}
    cached_messages.append(msg_copy)
  
  resp = client.chat.completions.create(
    model=MODEL,
    messages=cached_messages,
    tools=TOOLS,
    tool_choice="auto",
    reasoning_effort="minimal"
  )
  return resp.model_dump()


def run_chat_stream(messages: List[Dict]):
  """Stream chat completions token by token.
  
  Yields:
    Dict with 'type' field indicating chunk type:
    - {"type": "content", "delta": str} - text content chunk
    - {"type": "tool_calls", "tool_calls": [...]} - complete tool calls
    - {"type": "done", "message": dict, "usage": dict} - final message
  """
  if client is None:
    yield {"type": "content", "delta": "(LLM disabled: no OPENAI_API_KEY set)"}
    yield {"type": "done", "message": {"role": "assistant", "content": "(LLM disabled: no OPENAI_API_KEY set)"}, "usage": {}}
    return
  
  # Enable prompt caching by adding cache_control to system messages
  cached_messages = []
  for i, msg in enumerate(messages):
    msg_copy = msg.copy()
    # Mark the last system message for caching
    if msg.get("role") == "system" and i < len(messages) - 1 and messages[i + 1].get("role") != "system":
      msg_copy["cache_control"] = {"type": "ephemeral"}
    cached_messages.append(msg_copy)
    
  stream = client.chat.completions.create(
    model=MODEL,
    messages=cached_messages,
    tools=TOOLS,
    tool_choice="auto",
    stream=True
  )
  
  # Accumulate the full response as we stream
  accumulated_content = ""
  accumulated_tool_calls = []
  final_message = {"role": "assistant"}
  
  for chunk in stream:
    if not chunk.choices:
      continue
      
    delta = chunk.choices[0].delta
    finish_reason = chunk.choices[0].finish_reason
    
    # Stream content tokens
    if delta.content:
      accumulated_content += delta.content
      yield {"type": "content", "delta": delta.content}
    
    # Accumulate tool calls (they come in pieces)
    if delta.tool_calls:
      for tc_delta in delta.tool_calls:
        idx = tc_delta.index
        # Ensure we have enough slots
        while len(accumulated_tool_calls) <= idx:
          accumulated_tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        
        if tc_delta.id:
          accumulated_tool_calls[idx]["id"] = tc_delta.id
        if tc_delta.function:
          if tc_delta.function.name:
            accumulated_tool_calls[idx]["function"]["name"] = tc_delta.function.name
          if tc_delta.function.arguments:
            accumulated_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments
    
    # On finish, yield complete message
    if finish_reason:
      if accumulated_content:
        final_message["content"] = accumulated_content
      if accumulated_tool_calls:
        final_message["tool_calls"] = accumulated_tool_calls
        yield {"type": "tool_calls", "tool_calls": accumulated_tool_calls}
      
      # Get usage from final chunk if available
      usage = {}
      if hasattr(chunk, 'usage') and chunk.usage:
        usage = {
          "prompt_tokens": chunk.usage.prompt_tokens,
          "completion_tokens": chunk.usage.completion_tokens,
          "total_tokens": chunk.usage.total_tokens
        }
      
      yield {"type": "done", "message": final_message, "usage": usage}
      break