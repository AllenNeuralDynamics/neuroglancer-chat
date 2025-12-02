from typing import Dict
from uuid import uuid4


# For MVP: in-memory; replace with Redis/Postgres
_STATES: dict[str, Dict] = {}


def save_state(state: Dict) -> str:
    sid = str(uuid4())
    _STATES[sid] = state
    return sid


def load_state(sid: str) -> Dict:
    return _STATES[sid]