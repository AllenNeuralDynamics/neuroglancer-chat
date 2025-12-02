import uuid
from typing import Dict, List, Optional
from datetime import datetime

import polars as pl

MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB cap (matches uvicorn limit)


class UploadedFileRecord:
    def __init__(self, file_id: str, name: str, size: int, df: pl.DataFrame):
        self.file_id = file_id
        self.name = name
        self.size = size
        self.df = df

    def to_meta(self) -> dict:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "size": self.size,
            "n_rows": self.df.height,
            "n_cols": self.df.width,
            "columns": self.df.columns,
        }


class SummaryRecord:
    def __init__(
        self,
        summary_id: str,
        source_file_id: str,
        kind: str,
        df: pl.DataFrame,
        note: Optional[str] = None,
    ):
        self.summary_id = summary_id
        self.source_file_id = source_file_id
        self.kind = kind
        self.df = df
        self.note = note

    def to_meta(self) -> dict:
        return {
            "summary_id": self.summary_id,
            "source_file_id": self.source_file_id,
            "kind": self.kind,
            "n_rows": self.df.height,
            "n_cols": self.df.width,
            "columns": self.df.columns,
            "note": self.note,
        }


class PlotRecord:
    """Record of a generated plot with metadata."""
    def __init__(
        self,
        plot_id: str,
        source_id: str,
        plot_type: str,
        plot_html: str,
        plot_spec: dict,
        expression: Optional[str] = None,
    ):
        self.plot_id = plot_id
        self.source_id = source_id  # file_id or summary_id
        self.plot_type = plot_type
        self.plot_html = plot_html
        self.plot_spec = plot_spec  # {x, y, by, size, color, etc.}
        self.expression = expression  # Optional Polars query used to prep data
        self.created_at = datetime.now()
    
    def to_meta(self) -> dict:
        return {
            "plot_id": self.plot_id,
            "source_id": self.source_id,
            "plot_type": self.plot_type,
            "plot_spec": self.plot_spec,
            "expression": self.expression,
            "created_at": self.created_at.isoformat(),
        }


class DataMemory:
    """Ephemeral session-scoped data store for uploaded CSVs & derived summaries."""

    def __init__(self, max_summaries: int = 100):
        self.files: Dict[str, UploadedFileRecord] = {}
        self.summaries: Dict[str, SummaryRecord] = {}
        self.plots: Dict[str, PlotRecord] = {}
        self.max_summaries = max_summaries
        self.summary_order: List[str] = []  # Track insertion order for LRU

    def add_file(self, name: str, raw: bytes) -> dict:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"File too large ({len(raw)} bytes > {MAX_FILE_BYTES})")
        try:
            df = pl.read_csv(raw)
        except Exception as e:  # pragma: no cover - defensive
            raise ValueError(f"Failed to parse CSV: {e}") from e
        
        # Check for duplicate filename and replace if exists
        existing_fid = None
        for fid, rec in self.files.items():
            if rec.name == name:
                existing_fid = fid
                break
        
        if existing_fid:
            # Reuse existing file_id when replacing
            fid = existing_fid
        else:
            # Generate new file_id for new file
            fid = uuid.uuid4().hex[:8]
        
        rec = UploadedFileRecord(fid, name, len(raw), df)
        self.files[fid] = rec
        return rec.to_meta()

    def list_files(self) -> List[dict]:
        return [rec.to_meta() for rec in self.files.values()]

    def remove_file(self, file_id: str) -> bool:
        """Remove a file and all its derived summaries. Returns True if file existed."""
        if file_id not in self.files:
            return False
        
        # Remove the file
        del self.files[file_id]
        
        # Remove all summaries derived from this file
        to_remove = [sid for sid, rec in self.summaries.items() 
                     if rec.source_file_id == file_id]
        for sid in to_remove:
            del self.summaries[sid]
            # Also remove from order tracking
            if sid in self.summary_order:
                self.summary_order.remove(sid)
        
        return True

    def get_df(self, file_id: str) -> pl.DataFrame:
        if file_id not in self.files:
            raise KeyError(f"Unknown file_id: {file_id}")
        return self.files[file_id].df

    def add_summary(
        self, file_id: str, kind: str, df: pl.DataFrame, note: str | None = None
    ) -> dict:
        # Enforce max summaries limit (LRU eviction)
        if len(self.summaries) >= self.max_summaries:
            # Remove oldest summary
            if self.summary_order:
                oldest_id = self.summary_order.pop(0)
                if oldest_id in self.summaries:
                    del self.summaries[oldest_id]
        
        sid = uuid.uuid4().hex[:8]
        rec = SummaryRecord(sid, file_id, kind, df, note)
        self.summaries[sid] = rec
        self.summary_order.append(sid)
        return rec.to_meta()

    def list_summaries(self) -> List[dict]:
        return [rec.to_meta() for rec in self.summaries.values()]

    def get_summary_df(self, summary_id: str) -> pl.DataFrame:
        if summary_id not in self.summaries:
            raise KeyError(f"Unknown summary_id: {summary_id}")
        return self.summaries[summary_id].df

    def get_summary_record(self, summary_id: str) -> SummaryRecord:
        if summary_id not in self.summaries:
            raise KeyError(f"Unknown summary_id: {summary_id}")
        return self.summaries[summary_id]

    def add_plot(
        self, 
        source_id: str, 
        plot_type: str, 
        plot_html: str, 
        plot_spec: dict, 
        expression: Optional[str] = None
    ) -> dict:
        """Store a generated plot and return metadata."""
        plot_id = uuid.uuid4().hex[:8]
        rec = PlotRecord(plot_id, source_id, plot_type, plot_html, plot_spec, expression)
        self.plots[plot_id] = rec
        return rec.to_meta()

    def list_plots(self) -> List[dict]:
        """List all generated plots (metadata only, no HTML)."""
        return [rec.to_meta() for rec in self.plots.values()]

    def get_plot(self, plot_id: str) -> PlotRecord:
        """Retrieve full plot record including HTML."""
        if plot_id not in self.plots:
            raise KeyError(f"Unknown plot_id: {plot_id}")
        return self.plots[plot_id]


class InteractionMemory:
    """Simple rolling memory for recent interactions."""

    def __init__(self, max_items: int = 30, max_chars: int = 6000):
        self.events: List[str] = []
        self.max_items = max_items
        self.max_chars = max_chars

    def remember(self, interaction: str):
        self.events.append(interaction.strip())
        if len(self.events) > self.max_items:
            self.events = self.events[-self.max_items :]
        joined = " | ".join(self.events)
        if len(joined) > self.max_chars:
            while self.events and len(" | ".join(self.events)) > self.max_chars:
                self.events.pop(0)

    def recall(self) -> str:
        return " | ".join(self.events)
