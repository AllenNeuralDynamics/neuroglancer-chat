"""
Neuroglancer state pointer expansion utilities.

Handles expansion of JSON pointers (s3://, gs://, http(s)://) in Neuroglancer URLs
to canonical inline state URLs with percent-encoded JSON.
"""

import json
import urllib.parse
import re
from typing import Callable, Tuple, Any, Mapping, Optional

try:
    import boto3  # Optional; only needed for direct s3:// fetch
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False

try:
    from google.cloud import storage as gcs  # Optional; only needed for gs:// fetch
    _HAS_GCS = True
except ImportError:
    _HAS_GCS = False


# -------- Core Helpers --------

def _is_probably_json(text: str) -> bool:
    """Check if text looks like JSON."""
    text = text.strip()
    return text.startswith('{') and text.endswith('}')


def _percent_decode(fragment: str) -> str:
    """Decode percent-encoded fragment."""
    return urllib.parse.unquote(fragment)


def _percent_encode_minified(obj: Mapping[str, Any]) -> str:
    """Encode object as minified, percent-encoded JSON for Neuroglancer URLs."""
    raw = json.dumps(obj, separators=(',', ':'), sort_keys=False)
    # Safe chars: keep a small set unescaped (tolerant). Adjust if you want stricter.
    return urllib.parse.quote(raw, safe="!~*'()")


def _fetch_http(url: str, http_get: Optional[Callable[[str], str]] = None) -> str:
    """Fetch content from HTTP/HTTPS URL."""
    if http_get:
        return http_get(url)
    # Default simple implementation
    import urllib.request
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode('utf-8')


def _fetch_s3(url: str) -> str:
    """Fetch s3://bucket/key using boto3 (if available)."""
    if not _HAS_BOTO3:
        raise RuntimeError("boto3 not installed; install boto3 or provide a custom fetcher.")
    m = re.match(r'^s3://([^/]+)/(.+)$', url)
    if not m:
        raise ValueError(f"Not a valid s3 URL: {url}")
    bucket, key = m.group(1), m.group(2)
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj['Body'].read().decode('utf-8')


def _fetch_gs(url: str) -> str:
    """Fetch gs://bucket/key using google-cloud-storage (if available)."""
    if not _HAS_GCS:
        raise RuntimeError("google-cloud-storage not installed; install google-cloud-storage or provide a custom fetcher.")
    m = re.match(r'^gs://([^/]+)/(.+)$', url)
    if not m:
        raise ValueError(f"Not a valid gs URL: {url}")
    bucket_name, blob_name = m.group(1), m.group(2)
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.download_as_text()


def _default_fetch(url: str) -> str:
    """Default fetcher that handles s3://, gs://, and http(s):// URLs."""
    if url.startswith('s3://'):
        return _fetch_s3(url)
    elif url.startswith('gs://'):
        return _fetch_gs(url)
    elif url.startswith('http://') or url.startswith('https://'):
        return _fetch_http(url)
    else:
        raise ValueError(f"Unsupported pointer scheme for URL fetch: {url}")


# -------- Public API --------

def resolve_neuroglancer_pointer(
    fragment: str,
    fetcher: Callable[[str], str] | None = None
) -> Tuple[dict, bool]:
    """
    Resolve a Neuroglancer fragment (the part after '#!') into a state dict.

    Parameters
    ----------
    fragment : str
        Either inline (percent-encoded) JSON or a pointer URL (http(s)://, s3://, gs://).
    fetcher : callable, optional
        Custom fetcher(url) -> text. If not provided, uses default logic.

    Returns
    -------
    state_dict : dict
        Parsed Neuroglancer state
    was_pointer : bool
        True if we had to fetch it from a pointer; False if inline JSON.
        
    Raises
    ------
    ValueError
        If fragment is invalid JSON or pointer URL is malformed
    RuntimeError
        If required dependencies (boto3, google-cloud-storage) are missing
    """
    # Raw fragment may still be percent-encoded
    decoded = _percent_decode(fragment)

    # Case 1: Inline JSON
    if _is_probably_json(decoded):
        try:
            return json.loads(decoded), False
        except json.JSONDecodeError as e:
            raise ValueError(f"Fragment looked like JSON but failed to parse: {e}") from e

    # Case 2: Pointer (URL to JSON)
    fetcher = fetcher or _default_fetch
    try:
        json_text = fetcher(decoded)
    except Exception as e:
        raise ValueError(f"Failed to fetch content from pointer '{decoded}': {e}") from e
    
    try:
        state = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Fetched text is not valid JSON from pointer '{decoded}': {e}") from e
    return state, True


def neuroglancer_state_to_url(
    state: Mapping[str, Any],
    viewer_base_url: str
) -> str:
    """
    Serialize a Neuroglancer state dict to a canonical inline URL.
    
    Parameters
    ----------
    state : dict
        Neuroglancer state dictionary
    viewer_base_url : str
        Base URL of the Neuroglancer viewer
        
    Returns
    -------
    str
        Complete Neuroglancer URL with inline state
    """
    # Remove pointer reference if present
    state = dict(state)  # Make a copy to avoid modifying original
    state.pop('ng_link', None)
    
    frag = _percent_encode_minified(state)
    if viewer_base_url.endswith('/'):
        viewer_base_url = viewer_base_url.rstrip('/')
    return f"{viewer_base_url}/#!{frag}"


def expand_if_pointer_and_generate_inline(
    full_url: str,
    fetcher: Callable[[str], str] | None = None
) -> Tuple[str, dict, bool]:
    """
    Given a full viewer URL (or just a fragment), resolve and produce
    the canonical inline state URL.

    Parameters
    ----------
    full_url : str
        Complete Neuroglancer URL or just the fragment part
    fetcher : callable, optional
        Custom fetcher function for pointer resolution

    Returns
    -------
    canonical_url : str
        Neuroglancer URL with inline (percent-encoded) state
    state_dict : dict
        Parsed state dictionary
    was_pointer : bool
        True if original URL contained a pointer that was expanded
        
    Raises
    ------
    ValueError
        If URL format is invalid or pointer resolution fails
    RuntimeError
        If required cloud storage libraries are missing
    """
    # Split base and fragment
    if '#!' in full_url:
        base, fragment = full_url.split('#!', 1)
    else:
        # If only fragment provided
        base, fragment = '', full_url.lstrip('#!')
    
    state, was_pointer = resolve_neuroglancer_pointer(fragment, fetcher=fetcher)
    
    # Use provided base URL or fall back to a default
    if not base:
        base = "https://neuroglancer-demo.appspot.com"
    
    canonical = neuroglancer_state_to_url(state, base)
    return canonical, state, was_pointer


def is_pointer_url(url: str) -> bool:
    """
    Check if a Neuroglancer URL contains a JSON pointer.
    
    Parameters
    ----------
    url : str
        Full Neuroglancer URL or fragment
        
    Returns
    -------
    bool
        True if URL contains a pointer (s3://, gs://, http(s)://)
    """
    if '#!' not in url:
        return False
    
    _, fragment = url.split('#!', 1)
    decoded = _percent_decode(fragment)
    
    # Check if it's a pointer URL rather than inline JSON
    return not _is_probably_json(decoded)