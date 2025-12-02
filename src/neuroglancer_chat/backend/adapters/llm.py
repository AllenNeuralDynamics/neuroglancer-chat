import os, json
from typing import List, Dict
from openai import OpenAI

_API_KEY = os.getenv("OPENAI_API_KEY")
#MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # Configurable via env var
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")  # Configurable via env var

client = None
if _API_KEY:
  client = OpenAI(api_key=_API_KEY)

SYSTEM_PROMPT = """
You are Neuroglancer Chat, an assistant for neuroimaging data analysis and visualization.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 CRITICAL: CALL TOOLS IMMEDIATELY, NO PRE-EXPLANATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ WRONG: \"I'll create a plot...\" or \"Let me query the data...\"
✅ CORRECT: [Call tool immediately in first response]

Examples:
• \"plot x vs y\" → Call data_plot NOW (no text)
• \"show unique genes\" → Call data_query_polars NOW (no text)
• \"add annotation points\" → Call data_ng_annotations_from_data NOW (no text)

Brief context AFTER tool results is okay. Never explain before calling tools.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 TOOL SELECTION GUIDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA OPERATIONS:
• Preview/explore data → data_query_polars
• Create annotations from data → data_ng_annotations_from_data  
• Generate plots → data_plot
• Simple preview → data_preview
• Statistics → data_describe

NEUROGLANCER VISUALIZATION:
• Add annotation points/spheres/lines to viewer → data_ng_annotations_from_data
• "Plot xyz locations" → data_ng_annotations_from_data (NOT data_plot)
• "Visualize spots/points in viewer" → data_ng_annotations_from_data (NOT data_plot)
• Change camera/view → ng_set_view
• Adjust layer colors/ranges → ng_set_lut
• Add/modify layers → ng_add_layer
• Get state info → ng_state_summary
• Share view → ng_state_link (not state_save unless \"save\"/\"persist\")

DEFAULT BEHAVIORS:
• Data questions → Immediate tool call
• Multiple similar operations → Make parallel tool calls (5-8 per iteration)
• Unknown layer/state info → Call ng_state_summary first
• When user mentions "data" without file ID → Use most recent file from context

VISUALIZATION DISAMBIGUATION:
• "plot xyz" / "plot locations" / "visualize spots" → data_ng_annotations_from_data (add to Neuroglancer viewer)
• "plot x vs y" / "scatter plot" / "histogram" → data_plot (matplotlib chart in separate window)
• Default assumption: User wants to see data IN the Neuroglancer viewer, not external plots
• If ambiguous, prefer data_ng_annotations_from_data over data_plot

BATCH OPERATIONS - Creating Multiple Layers:
When user asks for "layer per gene" or "layer for each X":
1. First: Query unique values: df.select(pl.col('gene').unique())
2. Then: Make PARALLEL calls to data_ng_annotations_from_data (one per value)
   • Each call filters for ONE specific value
   • Each call creates ONE layer with ONE color
   • Example for 10 genes → Make 10 parallel tool calls in ONE iteration

PATTERN for "layer per gene":
```
# Iteration 1: Get unique genes
data_query_polars(expression="df.select(pl.col('gene').unique())")

# Iteration 2: Create all layers in parallel (5-8 at once)
data_ng_annotations_from_data(file_id='...', layer_name='Gene_Sst', filter_expression="df.filter(pl.col('gene')=='Sst')", color='#ff0000')
data_ng_annotations_from_data(file_id='...', layer_name='Gene_Vip', filter_expression="df.filter(pl.col('gene')=='Vip')", color='#00ff00')
data_ng_annotations_from_data(file_id='...', layer_name='Gene_Pvalb', filter_expression="df.filter(pl.col('gene')=='Pvalb')", color='#0000ff')
... (continue for all genes, batching 5-8 per iteration if needed)
```

ENTITY REFERENCE INTERPRETATION:
When user mentions a specific entity (cell, cluster, region, etc.) treat it as a FILTER CONSTRAINT:
• "Cell 74330 has X" → Include filter: (pl.col('cell_id') == 74330)
• "Show gene X in cell Y" → Include filter: (pl.col('cell_id') == Y) & (pl.col('gene') == X)
• "Cluster 5 contains..." → Include filter: (pl.col('cluster') == 5)
• "Region A shows..." → Include filter: (pl.col('region') == 'A')
• Multiple entities: "Cells 100 and 200" → Include filter: pl.col('cell_id').is_in([100, 200])

Always combine entity filters with other requested filters using & (AND).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 RESPONSE FORMAT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AFTER data_query_polars:
• Frontend renders table automatically
• Your job: Brief context only (e.g., \"Here are the unique genes.\")
• ❌ DON'T format data, show expressions, create markdown tables

AFTER data_plot:
• Frontend renders plot automatically
• Your job: Single sentence with a brief summary/rationale of your choice
• ❌ DON'T describe plot or summarize data

AFTER data_ng_annotations_from_data:
• Confirm briefly (e.g., \"Added 150 annotation points.\")

GENERAL:
• Keep answers concise
• Avoid redundant summaries
• Answer from 'Current viewer state summary' context if user only wants info (no tools needed)

Conversation context awareness:
- If you just returned data/results in the previous response, the user's next question likely refers to that data.
- When the user asks a follow-up question about filtering, counting, or analyzing data you just showed, they mean the data from your previous response.
- Before making a new query, check if you can answer from the data you just returned.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 DATA QUERY SYNTAX (Polars)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ALWAYS use Polars syntax. Available in namespace: 'df' (DataFrame) and 'pl' (Polars module).

FILTERING (use pl.col() for column references):
• Single condition: df.filter(pl.col('age') > 30)
• Multiple AND: df.filter((pl.col('age') > 30) & (pl.col('score') > 0.5))
• Multiple OR: df.filter((pl.col('type') == 'A') | (pl.col('type') == 'B'))
• String match: df.filter(pl.col('gene') == 'Sst')
• Null check: df.filter(pl.col('value').is_not_null())

GROUPING & AGGREGATION:
• Group + count: df.group_by('cluster').agg(pl.count())
• Group + stats: df.group_by('gene').agg(pl.mean('expression'), pl.max('intensity'))
• Multiple groups: df.group_by(['region', 'type']).agg(pl.first('x'), pl.first('y'), pl.first('z'))

SELECTION & SORTING:
• Select columns: df.select(['x', 'y', 'z', 'gene'])
• Unique values: df.select(pl.col('gene').unique())
• Sort descending: df.sort('volume', descending=True)
• Sort multiple: df.sort(['cluster', 'score'], descending=[False, True])

SAMPLING & LIMITING:
• Random sample: df.sample(n=100)
• First N rows: df.head(20)
• Limit: df.limit(50)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ ERROR HANDLING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 KEEP LOOPING: If a tool returns an error, make another tool call with corrections.
   Never stop after one error - you have 10 iterations to get it right. Correct and call again immediately,
   explain only after trying multiple fixes.

PROCESS:
1. Tool returns error → Read error message for specific issue
2. If there is something ambiguous about the user request, clarify with user first.
3. Make corrected tool call immediately (no text explanation to user)
4. If still error → Apply different correction and call again
5. ❌ DON'T: Stop after first error or retry identical expressions
"""

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
      "description":"Add annotation(s) to a layer using explicit coordinates. Use for: 1) Adding a single annotation at specific coordinates (provide center/type), 2) Adding multiple programmatically-defined annotations (provide items array). For annotations from uploaded CSV/dataframe data, use data_ng_annotations_from_data instead.",
      "parameters": {
        "type": "object",
        "properties": {
          "layer": {"type": "string", "description": "Name of annotation layer to add to"},
          "type": {"type": "string", "enum": ["point", "box", "ellipsoid"], "description": "Annotation type (for single annotation)"},
          "center": {
            "type": "object",
            "description": "Coordinates for single annotation",
            "properties": {
              "x": {"type": "number"},
              "y": {"type": "number"},
              "z": {"type": "number"}
            },
            "required": ["x", "y", "z"]
          },
          "size": {
            "type": "object",
            "description": "Size dimensions for box/ellipsoid (optional for single annotation)",
            "properties": {
              "x": {"type": "number"},
              "y": {"type": "number"},
              "z": {"type": "number"}
            }
          },
          "id": {"type": "string", "description": "Optional ID for single annotation"},
          "items": {
            "type": "array",
            "description": "Array of annotation objects (for bulk operations)",
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
        "required": ["layer"]
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
      "description": "Create Neuroglancer annotations (points/boxes/ellipsoids) from dataframe rows. Each row becomes one annotation.\n\nPATTERN: Always use file_id + filter_expression (inline filtering). DO NOT chain queries.\n\nEXAMPLE - Annotate cell 74330 where chan==638:\n  data_ng_annotations_from_data(\n    file_id='abc123',\n    filter_expression=\"df.filter((pl.col('chan')==638) & (pl.col('cell_id')==74330))\",\n    layer_name='Cell_74330',\n    center_columns=['x','y','z']\n  )\n\nEXAMPLE - Top cell per cluster with aggregation:\n  data_ng_annotations_from_data(\n    file_id='abc123',\n    filter_expression=\"df.group_by('cluster').first()\",\n    layer_name='Top_Cells',\n    center_columns=['x','y','z']\n  )\n\nEXAMPLE - Filter by gene name:\n  filter_expression=\"df.filter(pl.col('gene') == 'Sst')\"\n\nNOTE: Use Polars syntax (df.filter + pl.col). Pandas-style df[df['col']==val] is auto-translated but prefer Polars.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "Source CSV file ID (DEFAULT - use 99% of the time)"},
          "summary_id": {"type": "string", "description": "RARE: Only if you saved query with save_as. Default to file_id."},
          "layer_name": {"type": "string", "description": "Annotation layer name"},
          "annotation_type": {"type": "string", "enum": ["point", "box", "ellipsoid"], "default": "point"},
          "center_columns": {"type": "array", "items": {"type": "string"}, "default": ["x", "y", "z"], "description": "Column names for coordinates (e.g., ['centroid_x', 'centroid_y', 'centroid_z'])"},
          "size_columns": {"type": "array", "items": {"type": "string"}, "description": "For box/ellipsoid: width,height,depth column names"},
          "id_column": {"type": "string", "description": "Optional: column for annotation IDs (e.g., 'cell_id')"},
          "color": {"type": "string", "description": "Hex color (e.g., '#00ff00' green, '#ff0000' red)"},
          "filter_expression": {"type": "string", "description": "Filter/transform expression. Use Polars syntax. Examples: df.filter(pl.col('cluster')==3) or df.group_by('x').first()."},
          "limit": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 5000, "description": "Max annotations"}
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
      "description": "Execute query to preview data in interactive table. Use pandas or Polars syntax - both work (auto-translated).\n\nCOMMON PATTERNS:\n• Filter: df[df['age'] > 30] or df.filter(pl.col('age') > 30)\n• Group: df.groupby('cluster').agg({'score': 'max'}) or df.group_by('cluster').agg(pl.max('score'))\n• Unique: df['gene'].unique() or df.select(pl.col('gene').unique())\n• Sort: df.sort_values('volume', ascending=False) or df.sort('volume', descending=True)\n• Sample: df.sample(n=10)\n\nTIPS:\n• Use 'df' for dataframe, 'pl' for Polars functions\n• Include spatial columns (x,y,z) in aggregations for Neuroglancer links\n• pandas methods like groupby(), distinct() work (auto-converted)",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "ID of uploaded CSV file (most common)"},
          "summary_id": {"type": "string", "description": "ID of saved query result (only if you used save_as previously)"},
          "expression": {
            "type": "string",
            "description": "Query expression. Use pandas or Polars syntax. Examples: df[df['x']>5] or df.groupby('col')['val'].max() or df.select(pl.col('gene').unique())"
          },
          "save_as": {"type": "string", "description": "Optional: Save result with this name for reuse in subsequent queries"},
          "limit": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 10000, "description": "Maximum rows to return"}
        },
        "required": ["expression"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "data_plot",
      "description": "Generate interactive plot from dataframe. Use expression for filtering/aggregation. Pandas or Polars syntax both work.\n\nCOMMON PATTERNS:\n• Scatter raw data: plot_type='scatter', x='col1', y='col2'\n• Scatter filtered: expression='df[df.x > 5]', x='a', y='b'\n• Bar aggregated: expression='df.groupby(\"cluster\")[\"volume\"].mean()', plot_type='bar', x='cluster', y='volume'\n• Scatter colored: plot_type='scatter', x='a', y='b', by='category'\n\nAGGREGATION:\n• Mean by group: df.groupby('cluster')['volume'].mean()\n• Max by group: df.groupby('gene')['expr'].max()\n• Filter + aggregate: df[df.x>0].groupby('type')['count'].sum()",
      "parameters": {
        "type": "object",
        "properties": {
          "file_id": {"type": "string", "description": "Source file ID"},
          "summary_id": {"type": "string", "description": "Source summary ID (if using saved query)"},
          "plot_type": {
            "type": "string",
            "enum": ["scatter", "line", "bar", "heatmap"],
            "description": "scatter (x/y points), line (trends), bar (categorical), heatmap (matrix)"
          },
          "x": {"type": "string", "description": "X-axis column"},
          "y": {"type": "string", "description": "Y-axis column"},
          "by": {"type": "string", "description": "Grouping column for multiple series (scatter/line). NOT for bar plot aggregation."},
          "size": {"type": "string", "description": "Point size column (scatter only)"},
          "color": {"type": "string", "description": "Point color column (scatter only)"},
          "stacked": {"type": "boolean", "default": False, "description": "Stack bars (bar plot only)"},
          "title": {"type": "string", "description": "Plot title"},
          "expression": {
            "type": "string",
            "description": "Filtering/aggregation expression. Pandas or Polars syntax. Examples: df.sample(20) or df[df.x>5] or df.groupby('cluster')['volume'].mean()"
          },
          "save_plot": {"type": "boolean", "default": True, "description": "Store in workspace"},
          "interactive_override": {"type": "boolean", "description": "Force interactive on/off"}
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