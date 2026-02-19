import numpy as np
from typing import Tuple, Optional


# Placeholder: sample voxels via CloudVolume in ROI or random blocks


def sample_voxels(layer: str, roi: Optional[dict] = None) -> np.ndarray:
    # TODO: open CloudVolume("precomputed://s3://bucket/dataset/layer") and fetch
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, size=(2_000_000,), dtype=np.uint16)


def histogram(arr: np.ndarray, bins: int = 256) -> Tuple[np.ndarray, np.ndarray]:
    hist, edges = np.histogram(arr, bins=bins)
    return hist, edges