# M1/M3 joint closure candidate

This isolated branch combines M3 `af7a128e77490bdbd2d667eb3720102e23355a6b`
and the M1 PR #11 candidate `0e69fdf4a501f7c9d9003c8ac1735ce17bc10222`.
It retains the M3 Session factory and uses the original M1 `AssetFiles` in the
actual FastAPI application. The M1 Authority, Fencing, budget ledger, Runtime
source bytes and frozen V1.0 protocol are unchanged.

UNKNOWN correctly prevents replacement with `ATTEMPT_UNRESOLVED`. Existing
trusted M1 offline settlement can establish a terminal state before a new job
is admitted. M3 gains no settlement capability. Production billing, identity,
KMS and recovery service approval remain outside this candidate.

The original four supplemental tests are preserved in the task evidence. Their
unchanged rerun has three passes and one obsolete expectation failure: expecting
immediate replacement success while the prior reservation remains UNKNOWN.
The approved new safety tests require rejection, conservation of identity/hash
and budget, old-task nonpublication, and new-job success only after trusted M1
terminal confirmation. No original failure is silently converted to a pass.

Task evidence, JUnit, full logs, before/after HTTP response bytes and source
fingerprints are delivered under `reports/M1-M3-JOINT-CLOSURE-002` in the project
workspace. This branch is CI_ONLY and requires independent review. It does not
activate Generation DRAFT or authorize production deployment or merging dev.
