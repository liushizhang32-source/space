"""Authoritative verification requires BOTH public signature and durable current state."""
import time
import json
from contextlib import nullcontext
from cryptography.exceptions import InvalidSignature
import rfc8785
from .exceptions import AuthorizationError
from .schemas import parse_credential


class Verifier:
    def __init__(self, store, public_keys, *, clock=time.time):
        self.store, self.public_keys, self.clock = store, dict(public_keys), clock

    def verify(self, raw, *, expected_identity, expected_c2_sha256,
               expected_audience, expected_scope, _db=None):
        try:
            credential = parse_credential(raw)
        except (ValueError, TypeError):
            return 'MALFORMED'
        p = credential.payload
        key = self.public_keys.get(p.key_id)
        if key is None:
            return 'UNKNOWN_KEY'
        try:
            key.verify(bytes.fromhex(credential.signature), rfc8785.dumps(p.model_dump(mode='json')))
        except InvalidSignature:
            return 'INVALID_SIGNATURE'
        except (ValueError, TypeError):
            return 'MALFORMED'
        now = int(self.clock())
        if p.issued_at > now or p.not_before > now:
            return 'NOT_YET_VALID'
        if p.audience != expected_audience:
            return 'AUDIENCE_MISMATCH'
        if p.scope != expected_scope:
            return 'SCOPE_MISMATCH'
        if p.identity != expected_identity:
            return 'IDENTITY_MISMATCH'
        if p.c2_sha256 != expected_c2_sha256:
            return 'C2_HASH_MISMATCH'
        try:
            with (self.store.transaction() if _db is None else nullcontext(_db)) as db:
                row = db.execute('SELECT * FROM authorization WHERE jti=?', (p.jti,)).fetchone()
                if row is None:
                    return 'UNKNOWN_JTI'
                if row['nonce'] != p.nonce:
                    return 'UNKNOWN_NONCE'
                if row['credential'] != credential.model_dump_json():
                    return 'RECORD_MISMATCH'
                self.store.check_decision(db,p)
                if row['status'] == 'REVOKED':
                    return 'REVOKED'
                if p.expires_at <= now or row['status'] == 'EXPIRED':
                    self.store.expire(db,p.jti,now)
                    return 'EXPIRED'
                self.store.check_current(db, p.identity, p.c2_sha256)
            return 'VALID'
        except AuthorizationError as exc:
            return exc.status
        except (ValueError, TypeError, KeyError):
            return 'BLOCKED'


def downstream_allows(verify_call, *args, **kwargs):
    """Fake M2/M4 contract adapter: exceptions, timeouts and unknown statuses deny."""
    try:
        return verify_call(*args, **kwargs) == 'VALID'
    except Exception:
        return False
