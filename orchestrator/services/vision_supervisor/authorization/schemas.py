"""Strict JSON boundary. Duplicate keys, type coercion and unknown fields fail closed."""
import json
from .models import Credential
from ..supervisor import unique_json


def parse_credential(raw):
    if type(raw) is not bytes or len(raw) > 16384:
        raise ValueError('Invalid credential input')
    # validate_json permits the existing dataclass on a strict JSON boundary.
    return Credential.model_validate_json(json.dumps(unique_json(raw)))


def credential_schema():
    return Credential.model_json_schema()
