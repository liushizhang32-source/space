"""Production route is deny-only. Authenticated fake router is for offline tests."""
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .models import VerifyRequest
from ..supervisor import unique_json

PATH = '/internal/gate-authorizations/verify'
router = APIRouter()

# OpenAPI metadata only. This does not mount or enable offline_router.
BLOCKED_RESPONSE_DOC = {
    503: {
        'description': 'Production verification is disabled; no credential is consumed.',
        'content': {'application/json': {
            'schema': {
                'type': 'object', 'additionalProperties': False,
                'required': ['status', 'reason'],
                'properties': {
                    'status': {'type': 'string', 'const': 'BLOCKED'},
                    'reason': {'type': 'string', 'const': 'Production service authentication, key custody and lifecycle integration unproven'},
                },
            },
            'example': {'status': 'BLOCKED', 'reason': 'Production service authentication, key custody and lifecycle integration unproven'},
        }},
    },
}


@router.post(PATH, responses=BLOCKED_RESPONSE_DOC)
async def production_blocked():
    return JSONResponse({'status':'BLOCKED', 'reason':'Production service authentication, key custody and lifecycle integration unproven'}, status_code=503)


def offline_router(verifier, authenticate, resolve_context=None):
    """Explicitly OFFLINE. Server-bound resolver never trusts body/payload context.

    Default compatibility fixture requires exactly one current asset. Real service
    task assignment and authentication are absent; this router is never mounted by main.
    """
    result = APIRouter()

    @result.post(PATH)
    async def verify(request: Request):
        # Authentication is checked before body parsing or credential work.
        try:
            audience = authenticate(request)
        except Exception:
            audience = None
        if audience not in {'M2','M4'}:
            return JSONResponse({'status':'UNAUTHENTICATED'}, status_code=401)
        raw = await request.body()
        if len(raw) > 32768:
            return JSONResponse({'status':'MALFORMED'}, status_code=400)
        try:
            body = VerifyRequest.model_validate_json(json.dumps(unique_json(raw)))
        except (ValueError, TypeError):
            return JSONResponse({'status':'MALFORMED'}, status_code=400)
        if body.expected_audience != audience:
            return JSONResponse({'status':'AUDIENCE_MISMATCH'}, status_code=403)
        from .models import SCOPES
        from ..supervisor import Identity
        from .exceptions import AuthorizationError
        if body.expected_scope != SCOPES[audience]:
            return JSONResponse({'status':'SCOPE_MISMATCH'}, status_code=403)
        try:
            with verifier.store.transaction() as db:
                if resolve_context is None:
                    rows = db.execute('SELECT identity,c2_sha256 FROM current_asset WHERE enabled=1').fetchall()
                    if len(rows) != 1:
                        raise AuthorizationError('BLOCKED')
                    identity = Identity(**json.loads(rows[0]['identity']))
                    digest = rows[0]['c2_sha256']
                else:
                    # Bound by the test harness to an assigned task; no body input.
                    identity, digest = resolve_context(audience)
                if body.expected_identity != identity:
                    status = 'IDENTITY_MISMATCH'
                elif body.expected_c2_sha256 != digest:
                    status = 'C2_HASH_MISMATCH'
                else:
                    status = verifier.verify(body.credential.model_dump_json().encode(), _db=db,
                        expected_identity=identity, expected_c2_sha256=digest,
                        expected_audience=audience, expected_scope=SCOPES[audience])
        except Exception:
            status = 'BLOCKED'
        return JSONResponse({'status':status}, status_code=503 if status=='BLOCKED' else 200)
    return result
