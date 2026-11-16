"""Independent internal wire model; the frozen seven-field Identity is reused."""
from dataclasses import asdict
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..supervisor import Identity

SCOPES = {'M2': 'task.consume', 'M4': 'page.assets.read'}


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class Payload(StrictModel):
    schema_version: Literal['gate-authorization/0.1']
    alg: Literal['Ed25519']
    issuer: Literal['M1']
    audience: Literal['M2', 'M4']
    authorization_id: str = Field(min_length=1)
    jti: str = Field(min_length=1)
    nonce: str = Field(min_length=1)
    gate_decision_id: str = Field(min_length=1)
    # Dataclass field order/name/meaning comes from the frozen M1 owner source.
    identity: Identity
    c2_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    scope: Literal['task.consume', 'page.assets.read']
    issued_at: int = Field(ge=0, le=9007199254740991)
    not_before: int = Field(ge=0, le=9007199254740991)
    expires_at: int = Field(ge=0, le=9007199254740991)
    key_id: str = Field(min_length=1)

    @model_validator(mode='after')
    def consistent(self):
        i = asdict(self.identity)
        if any(type(i[k]) is not str or not i[k] for k in
               ('job_id', 'page_id', 'generation_id', 'attempt_id', 'fencing_token')):
            raise ValueError('Invalid Identity strings')
        if any(type(i[k]) is not int or not 1 <= i[k] <= 9007199254740991
               for k in ('input_revision', 'epoch')):
            raise ValueError('Invalid Identity counters')
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError('Invalid time interval')
        if self.expires_at - self.issued_at > 300:
            raise ValueError('Maximum lifetime is 300 seconds')
        if self.scope != SCOPES[self.audience]:
            raise ValueError('Audience/scope pair forbidden')
        return self


class Credential(StrictModel):
    payload: Payload
    signature: str = Field(pattern=r'^[0-9a-f]{128}$')


class VerifyRequest(StrictModel):
    credential: Credential
    expected_identity: Identity
    expected_c2_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_audience: Literal['M2', 'M4']
    expected_scope: Literal['task.consume', 'page.assets.read']
