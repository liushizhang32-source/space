"""G01/G06/G07: Ed25519 via cryptography, strict integer-only JCS profile.

RFC8785 property order is UTF-16, not Python Unicode code point order.
This protocol accepts only safe integers, never floating JSON numbers.
"""
import base64
import hashlib
import json
import re
from dataclasses import dataclass
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class Denied(ValueError):
    """Safe error text, never echo untrusted payloads, tokens or credentials."""


def need(value, message='security validation rejected'):
    if not value:
        raise Denied(message)


def integer(value, minimum=0, maximum=9007199254740991):
    need(type(value) is int and minimum <= value <= maximum, 'integer outside protocol bounds')
    return value


def fields(value, names):
    need(type(value) is dict and set(value) == set(names), 'unknown or missing fields')


def canonical(value):
    """RFC8785-compatible safe-integer subset; reject all unsupported numbers."""
    def encode(v):
        if v is None: return 'null'
        if type(v) is bool: return 'true' if v else 'false'
        if type(v) is int:
            integer(v, -9007199254740991)
            return str(v)
        if type(v) is str:
            need(not any(0xD800 <= ord(c) <= 0xDFFF for c in v), 'invalid Unicode')
            return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
        if type(v) is list: return '[' + ','.join(encode(i) for i in v) + ']'
        if type(v) is dict:
            need(all(type(k) is str for k in v), 'non-string object key')
            for k in v: encode(k)
            return '{' + ','.join(encode(k)+':'+encode(v[k]) for k in sorted(v,key=lambda k:k.encode('utf-16be'))) + '}'
        raise Denied('unsupported JSON value (floating numbers prohibited)')
    return encode(value).encode('utf-8')


def parse(raw, *, require_canonical=False):
    need(type(raw) is bytes and len(raw) <= 2_000_000, 'invalid JSON size/type')
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out, 'duplicate JSON key')
            out[k]=v
        return out
    def bad(_): raise Denied('unsupported JSON number')
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_float=bad,parse_constant=bad)
        encoded=canonical(value)
    except (UnicodeError,ValueError,RecursionError,TypeError):
        raise Denied('invalid strict JSON') from None
    if require_canonical: need(raw==encoded,'noncanonical wire encoding')
    return value


def sha(raw):
    need(type(raw) is bytes, 'raw bytes required')
    return hashlib.sha256(raw).hexdigest()


def b64(raw): return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


CLAIMS=set('issuer audience approved_by purpose provider model region max_calls max_seconds max_cost_cny_fen input_manifest_sha256 prompt_sha256 policy_sha256 issued_at not_before expires_at jti nonce key_id schema_version project_id budget_id approval_id'.split())
DOMAIN=b'M1-M3-POC-SECURITY-v1\x00'


def validate_claims(c):
    fields(c,CLAIMS)
    for k in CLAIMS-{'max_calls','max_seconds','max_cost_cny_fen','issued_at','not_before','expires_at'}:
        need(type(c[k]) is str and 0<len(c[k])<=256,'invalid claim string')
        need(c[k].strip().lower() not in {'tbd','todo','pending','unknown','placeholder','未批准','待批准','待定'},'unapproved placeholder')
    need(c['issuer']=='M1' and c['audience']=='M3','issuer/audience rejected')
    need(c['schema_version']=='1.0','unsupported schema version')
    need(c['project_id']=='paperbook-ai' and c['budget_id']=='m3-poc-cny-total','project/budget rejected')
    integer(c['max_calls'],1);integer(c['max_seconds'],1);integer(c['max_cost_cny_fen'],1,15000)
    for k in ('issued_at','not_before','expires_at'): integer(c[k])
    need(c['issued_at']<=c['not_before']<c['expires_at'],'invalid validity interval')
    for k in ('input_manifest_sha256','prompt_sha256','policy_sha256'):
        need(re.fullmatch('[0-9a-f]{64}',c[k]) is not None,'invalid digest')
    for k in ('jti','nonce'): need(re.fullmatch('[0-9a-f]{32}',c[k]) is not None,'invalid unique identifier')


class DisabledSigner:
    def sign(self, _message): raise Denied('production signer unavailable: secure key storage not provisioned')


@dataclass(frozen=True)
class TrustedKey:
    public: Ed25519PublicKey
    valid_from: int
    valid_until: int
    revoked: bool=False


class Verifier:
    """G06: public keys only; trusted registry never fetches a key URL."""
    def __init__(self, keys, clock):
        self.keys=dict(keys); self.clock=clock

    def verify(self, raw, *, historical=False):
        env=parse(raw,require_canonical=True)
        fields(env,{'protected','claims','signature'})
        p=env['protected']; fields(p,{'alg','typ','key_id'})
        need(p['alg']=='Ed25519' and p['typ']=='POC_APPROVAL_TOKEN','algorithm/type rejected')
        c=env['claims']; validate_claims(c)
        need(p['key_id']==c['key_id'],'key identifier mismatch')
        key=self.keys.get(p['key_id']); now=integer(self.clock())
        need(type(key) is TrustedKey and not key.revoked,'unknown/revoked key')
        need(key.valid_from<=c['issued_at']<key.valid_until,'key validity rejected')
        if not historical:
            need(c['not_before']<=now<c['expires_at'],'token not currently valid')
        s=env['signature'];need(type(s) is str and re.fullmatch('[A-Za-z0-9_-]{86}',s) is not None,'invalid signature encoding')
        try:
            decoded=base64.b64decode(s+'==',altchars=b'-_',validate=True)
            need(len(decoded)==64 and b64(decoded)==s,'noncanonical signature encoding')
            key.public.verify(decoded,DOMAIN+canonical({'protected':p,'claims':c}))
        except (InvalidSignature,ValueError):
            raise Denied('signature rejected') from None
        return c
