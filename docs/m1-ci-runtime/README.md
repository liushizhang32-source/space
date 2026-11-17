# M1-owned CI runtime V0.8.1

Status: CI_ONLY. M1 review and owner merge approval are pending.

Current PROPOSED protocol candidate: the following original-kit account is
historical provenance. `source-audit.json` and the original SHA list are retained
unchanged. The candidate retains 27 original runtime files and explicitly changes
only `authority.py` (anchor output metadata/revocations) and `recovery.py` (bounded
Windows sharing retry). The separate
`docs/protocols/M1_RUNTIME_PROPOSED_SOURCE_SHA256.json` binds the original manifest
and both exact before/after hashes; CI checks every byte and never skips the gate.
This profile is PROPOSED/CI_ONLY, not M1 owner sign-off or production readiness.
The new opt-in private profile is local+blocked only; its main/TTS wiring is
described in P2. The historical statement "main.py is unchanged" below applies
only to the original kit, not this candidate's explicit opt-in factory wiring.

The 29 runtime files are byte-for-byte copies from M1's validated offline kit
V0.8.1, archive SHA-256
`5cfbbbebbdcb16aefb52c0e634291f06d929c5d778594f74cd5e9c0df957dad1`.
See `source-audit.json` and `M1_RUNTIME_SOURCE_SHA256.txt` for provenance.
M1 owns maintenance and must review this dependency before merge.

This is an offline reference implementation for CI. It does not establish
production identity, production KMS, production HTTP authorization, paid provider
access, or activation of Generation Contract DRAFT. No production deployment is
authorized. Production protected routers remain deny-only; main.py is unchanged.

M1 regression tests and frozen M1/M2 protocol evidence are copied unchanged from
the same archive. Existing frozen schemas and all existing tests are unchanged.
The source workspace has untracked files outside the kit; those are excluded.

PR #10 adds 50 tests to the existing 134 vendor tests. Its integration branch
must separately update the strict CI inventory to 184 after this dependency is
available. The M1 dependency alone retains dev's 134-test inventory.
