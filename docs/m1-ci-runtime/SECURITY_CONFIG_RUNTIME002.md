# M1-M3-RUNTIME-002 security configuration candidate

Status: CI_ONLY; independent acceptance and owner merge approval are required.

The real orchestrator Settings now uses the V0.8.1 configuration checks. The real
create_app startup mounts the existing, unchanged AssetFiles implementation.
Only local/dev/production and blocked/offline_mock are accepted. offline_mock
requires local. Missing asset mode defaults to blocked; invalid values fail
before Storage is created. No protected production router is enabled.

Deployment impact requiring owner approval: old implicit static publication is
replaced by deny-by-default publication. No deployment is performed by this PR.
For an explicitly isolated local demonstration, set:

```powershell
$env:M1_DEPLOYMENT_ENV = 'local'
$env:M1_ASSET_MODE = 'offline_mock'
$env:GENERATION_BACKEND = 'mock'
python -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000
```

The unchanged V0.8.1 policy permits final demo resources only. OCR/VLM/refs,
sidecars and manifests remain blocked even in local mode. dev/production with
blocked can initialize, but cannot publish assets. Unknown environment values
never fall back to local.

The prior HTTP harness expected anonymous OCR/VLM JSON downloads. That
expectation conflicts with V0.8.1's explicit C1/C2 denial. The candidate keeps
the same complete Schema/page assertions on server-owned fixture bytes and
adds HTTP 503/BLOCKED assertions. It does not open C1/C2 to satisfy the old
transport expectation. This exposure change also requires owner approval.

All original M1 tests remain byte-identical. The new required Windows
m1-runtime job executes every test_m1_*.py: 226 original tests plus 16 real-app
configuration and mount tests, exactly 242 with no skipped/xfail results.
Windows is required for the original worker Job Object containment tests; CI
does not replace those with weaker Linux process groups. The aggregate summary
requires this job, its JUnit evidence and the same resolved SHA as the eight
existing groups. Existing media guard restrictions remain in effect.

The runner passes only an isolated local/offline environment and test-owned
temporary paths to reviewed M1 tests. It inherits no production credentials or
provider configuration. It does not claim to be a hostile-code sandbox.

Runtime 29/29 bytes, frozen M1/M2 V1.0, Token/budget core and Generation DRAFT
remain unchanged. Production identity, KMS, billing and paid providers remain
unprovisioned. No PRODUCTION_READY claim is made.
