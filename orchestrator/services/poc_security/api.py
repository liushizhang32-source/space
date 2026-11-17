"""G03: fail-closed production admission, no key/provider/env loading."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse


router=APIRouter()

# Documentation only: the handler below still returns its original JSONResponse.
BLOCKED_RESPONSE_DOC = {
    503: {
        'description': 'Production admission is disabled; no authorization is performed.',
        'content': {'application/json': {
            'schema': {
                'type': 'object', 'additionalProperties': False,
                'required': ['ok', 'status', 'message'],
                'properties': {
                    'ok': {'type': 'boolean', 'const': False},
                    'status': {'type': 'string', 'const': 'BLOCKED'},
                    'message': {'type': 'string', 'const': 'Production authorization, key custody, egress and billing evidence are not provisioned'},
                },
            },
            'example': {'ok': False, 'status': 'BLOCKED', 'message': 'Production authorization, key custody, egress and billing evidence are not provisioned'},
        }},
    },
}


@router.post('/internal/generation/submit', responses=BLOCKED_RESPONSE_DOC)
@router.post('/internal/approvals/issue', responses=BLOCKED_RESPONSE_DOC)
@router.post('/internal/approvals/verify', responses=BLOCKED_RESPONSE_DOC)
async def production_disabled():
    return JSONResponse(status_code=503,content={'ok':False,'status':'BLOCKED','message':'Production authorization, key custody, egress and billing evidence are not provisioned'})
