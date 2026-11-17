"""The only issuance entry point reruns Gate.accept; no Handoff issuance API."""
from dataclasses import asdict
import json
import time
import uuid
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .models import Payload, Credential, SCOPES
from .exceptions import AuthorizationError
from ..supervisor import VisionError
from .decisions import evaluate


class Issuer:
    def __init__(self, gate, store, *, key_id=None, test_private_key=None,
                 offline_test=False, clock=time.time):
        self.gate, self.store, self.clock = gate, store, clock
        self.key_id, self._key = key_id, test_private_key
        self.offline_test = offline_test

    def issue(self, record, fences, c1, c2, size, *, audience, scope, request_id, ttl=120):
        # No production custody implementation is supplied in this candidate.
        if not self.offline_test or not isinstance(self._key, Ed25519PrivateKey) or not self.key_id:
            raise AuthorizationError('BLOCKED')
        if audience not in SCOPES or scope != SCOPES[audience]:
            raise AuthorizationError('SCOPE_MISMATCH')
        if type(ttl) is not int or not 1 <= ttl <= 300 or type(request_id) is not str or not request_id:
            raise AuthorizationError('MALFORMED')
        with fences.lock:
            self.store.expire_due(int(self.clock()))
            handoff, decision_id = evaluate(self.gate,self.store,record,fences,c1,c2,size,
                                           now=int(self.clock()), audience=audience,
                                           scope=scope, operation_id=request_id)
            fences.check(record, handoff.identity)
            now = int(self.clock())
            binding = rfc8785.dumps(dict(identity=asdict(handoff.identity),
                c2_sha256=handoff.c2_sha256, audience=audience, scope=scope,
                key_id=self.key_id, ttl=ttl)).decode()
            with self.store.transaction() as db:
                self.store.check_current(db, handoff.identity, handoff.c2_sha256)
                existing = db.execute('SELECT * FROM authorization WHERE request_id=?', (request_id,)).fetchone()
                if existing:
                    if existing['binding'] != binding:
                        raise AuthorizationError('IDEMPOTENCY_CONFLICT')
                    if existing['status'] != 'ACTIVE' or existing['expires_at'] <= now:
                        raise AuthorizationError('REVOKED' if existing['status']=='REVOKED' else 'EXPIRED')
                    original = Credential.model_validate_json(existing['credential'])
                    self.store.check_decision(db,original.payload)
                    return original
                p = Payload(schema_version='gate-authorization/0.1', alg='Ed25519', issuer='M1',
                    audience=audience, authorization_id=uuid.uuid4().hex, jti=uuid.uuid4().hex,
                    nonce=uuid.uuid4().hex, gate_decision_id=decision_id,
                    identity=handoff.identity, c2_sha256=handoff.c2_sha256, scope=scope,
                    issued_at=now, not_before=now, expires_at=now+ttl, key_id=self.key_id)
                self.store.check_decision(db,p,require_link=False)
                credential = Credential(payload=p, signature=self._key.sign(
                    rfc8785.dumps(p.model_dump(mode='json'))).hex())
                db.execute('''INSERT INTO authorization VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',NULL,NULL)''',
                    (p.authorization_id, p.jti, p.nonce, request_id, binding,
                     credential.model_dump_json(), json.dumps(asdict(p.identity)), p.c2_sha256,
                     p.audience, p.scope, p.key_id, p.issued_at, p.expires_at))
                db.execute('INSERT INTO authorization_decision VALUES (?,?)',
                           (p.authorization_id,p.gate_decision_id))
                db.execute('INSERT INTO audit(authorization_id,action,at,reason) VALUES (?,?,?,?)',
                           (p.authorization_id,'ISSUED',now,'offline Gate.accept success'))
                # Do not return a signature until the transaction has committed.
            return credential
