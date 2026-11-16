# M1-owned CI runtime V0.8.1

Status: CI_ONLY. M1 review and owner merge approval are pending.

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
