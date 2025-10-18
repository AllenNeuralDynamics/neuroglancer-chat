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
You are Neurogabber, a helpful assistant for Neuroglancer.

CRITICAL: TAKE ACTION FIRST, EXPLAIN LATER. Use tools immediately when the user asks about data.

Decision rules:
- DEFAULT TO ACTION: When in doubt, call a tool. Don't ask permission or explain first.
- Data questions = IMMEDIATE tool call. Examples: "what are the unique values?", "how many rows?", "show me X" → call the tool NOW in your first response.
- If the user only wants information answer directly from the provided 'Current viewer state summary' (no tools).
- If the user wants to modify the view/viewer (camera, LUTs, annotations, layers) call the corresponding tool(s).
- If unsure of layer names or ranges, call ng_state_summary first (detail='standard' unless user requests otherwise).
- After performing modifications, if the user requests a link or updated view, call ng_state_link (NOT state_save) to return a masked markdown hyperlink. Only call state_save when explicit persistence is requested (e.g. 'save', 'persist', 'store').
- Do not paste raw Neuroglancer URLs directly; always rely on ng_state_link for sharing the current view.

Dataframe rules - ACTION REQUIRED:
- ANY question about CSV/dataframe content = IMMEDIATE tool call. Do NOT respond with text first.
- When the user mentions "data", "dataframe", "file", or "csv" without specifying which file, ALWAYS use the most recent file (shown in Data context).
- Questions like "what are the unique values in X?" or "how many Y?" or "show me Z" → call data_query_polars IMMEDIATELY.
- For simple operations, use specific tools (data_preview, data_describe).
- For complex queries (multiple filters, aggregations, computed columns, sorting), use data_query_polars with a Polars expression.
- In data_query_polars: use 'df' for the dataframe and 'pl' for Polars functions. All standard Polars operations are supported.
- ⚠️ CRITICAL: This is POLARS not pandas. NEVER use groupby() - it will ERROR. ALWAYS use group_by() with underscore.
- ⚠️ WRONG: df.groupby('col') ❌ RIGHT: df.group_by('col') ✓
- Common Polars patterns (NOTE THE UNDERSCORES):
  * Grouping: df.group_by('col').agg(pl.col('value').max())  [NOT groupby!]
  * Filtering: df.filter(pl.col('x') > 5)
  * Selecting: df.select(['col1', 'col2'])
  * Sorting: df.sort('col') or df.sort('col', descending=True)
  * Unique values: df.select(pl.col('col').unique())
  * Sampling: df.sample(n=10) or df.sample(n=10, seed=42) for reproducibility
- If you want to reuse a query result, use save_as parameter to store it as a summary table, then reference it with summary_id in subsequent queries.
- CRITICAL: When you receive tool results from data_query_polars, the result includes an "expression" field. You MUST display this expression in a Python code block in your response to the user.
- Format the query result like this:
  1. Show the Polars expression in a code block: ```python\n{expression}\n```
  2. Then present the data results (table, count, or summary)
  3. Example: "Here are the results:\n\n```python\ndf.group_by('cluster_label').agg(pl.col('log_volume').max())\n```\n\n| cluster_label | log_volume |\n..."

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
      "description": "Add a new Neuroglancer layer (image, segmentation, or annotation). Idempotent if name exists.",
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
          "visible": {"type": "boolean", "default": True}
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