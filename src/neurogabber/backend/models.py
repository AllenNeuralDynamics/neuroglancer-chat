from typing import Optional, Literal, Union, List
from pydantic import BaseModel


class Vec3(BaseModel):
    x: float; y: float; z: float


class SetView(BaseModel):
    center: Vec3
    zoom: Union[Literal["fit"], float] = "fit"
    orientation: Literal["xy","yz","xz","3d"] = "xy"


class SetLUT(BaseModel):
    layer: str
    vmin: float
    vmax: float


class Annotation(BaseModel):
    id: Optional[str] = None
    type: Literal["point","box","ellipsoid"]
    center: Vec3
    size: Optional[Vec3] = None # for box/ellipsoid


class AddAnnotations(BaseModel):
    layer: str
    items: List[Annotation]


class HistogramReq(BaseModel):
    layer: str
    roi: Optional[dict] = None # {bbox: [x0,y0,z0,x1,y1,z1]} or similar


class IngestCSV(BaseModel):
    file_id: str # uploaded handle or S3 key


class SaveState(BaseModel):
    pass


# Neuroglancer state management
class AddLayer(BaseModel):
    name: str
    layer_type: Literal["image", "segmentation", "annotation"] = "image"
    source: Union[str, dict, None] = None
    visible: bool = True
    annotation_color: Optional[str] = None  # Hex color or color name for annotation layers


class SetLayerVisibility(BaseModel):
    name: str
    visible: bool = True


class StateLoad(BaseModel):
    link: str
    default_settings: Optional[dict] = None  # User's preferred defaults from settings panel


class StateSummary(BaseModel):
    detail: Literal["minimal", "standard", "full"] = "standard"


# Data tools
class DataInfo(BaseModel):
    file_id: str
    sample_rows: int = 5


class DataPreview(BaseModel):
    file_id: str
    n: int = 10


class DataDescribe(BaseModel):
    file_id: str


class DataQuery(BaseModel):
    file_id: Optional[str] = None
    summary_id: Optional[str] = None
    expression: str
    save_as: Optional[str] = None
    limit: int = 100


class DataPlot(BaseModel):
    file_id: Optional[str] = None
    summary_id: Optional[str] = None
    plot_type: Literal["scatter", "line", "bar", "heatmap"] = "scatter"
    x: str
    y: str
    by: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    stacked: bool = False
    title: Optional[str] = None
    expression: Optional[str] = None
    save_plot: bool = True
    width: int = 700
    height: int = 400
    interactive_override: Optional[bool] = None


class NgViewsTable(BaseModel):
    file_id: Optional[str] = None
    summary_id: Optional[str] = None
    sort_by: Optional[str] = None
    descending: bool = True
    top_n: int = 5
    id_column: str = "cell_id"
    center_columns: List[str] = ["x", "y", "z"]
    include_columns: Optional[List[str]] = None
    lut: Optional[dict] = None
    annotations: bool = False
    link_label_column: Optional[str] = None


class NgAnnotationsFromData(BaseModel):
    file_id: Optional[str] = None
    summary_id: Optional[str] = None
    layer_name: str
    annotation_type: Literal["point", "box", "ellipsoid"] = "point"
    center_columns: List[str] = ["x", "y", "z"]
    size_columns: Optional[List[str]] = None  # For box/ellipsoid: [width, height, depth]
    id_column: Optional[str] = None
    color: Optional[str] = None  # Hex color like '#00ff00' for green
    filter_expression: Optional[str] = None  # Optional Polars filter before creating annotations
    limit: int = 1000  # Max annotations to create


class NgSetViewerSettings(BaseModel):
    showScaleBar: Optional[bool] = None
    showDefaultAnnotations: Optional[bool] = None
    showAxisLines: Optional[bool] = None
    layout: Optional[Literal["xy", "xz", "yz", "3d", "4panel"]] = None


# Chat
class ChatMessage(BaseModel):
    role: Literal["user","assistant","tool"]
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]