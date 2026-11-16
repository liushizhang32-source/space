"""Candidate protected read boundary; no legacy fallback on verification failure."""
from .exceptions import AuthorizationError
from contextlib import nullcontext


class AuthorizedAssetReader:
    def __init__(self, verifier, private_store):
        self.verifier, self.private_store = verifier, private_store

    def read(self, page_id, raw, **expected):
        if page_id != expected['expected_identity'].page_id:
            raise AuthorizationError('IDENTITY_MISMATCH')
        # Never enter another writer (or acquire Fences) inside a caller-owned
        # transaction on this ledger. No caller transaction is committed here.
        self.verifier.store.require_transaction_owner()
        fences = getattr(self.private_store, 'fences', None)
        with (fences.lock if fences is not None else nullcontext()):
            # This Reader owns both short transactions. Rejections are raised
            # only AFTER commit, so EXPIRED/audit cannot be rolled back by them.
            with self.verifier.store.transaction() as db:
                status = self.verifier.verify(raw, _db=db, **expected)
            if status != 'VALID':
                raise AuthorizationError(status)
            # Read immutable bytes outside the SQLite write transaction. A second
            # committed verification is the release linearization point: changes
            # during IO deny the result, with no cache/history fallback.
            accessor = getattr(self.private_store,'_read_authorized_snapshot',self.private_store.read)
            result = accessor(page_id)
            if result is None:
                raise AuthorizationError('BLOCKED')
            manifest, contents = result
            from dataclasses import asdict
            import hashlib
            if manifest['identity'] != asdict(expected['expected_identity']):
                raise AuthorizationError('IDENTITY_MISMATCH')
            raw_c2 = contents.get(f'json/{page_id}_vlm.json')
            if raw_c2 is None or hashlib.sha256(raw_c2).hexdigest() != expected['expected_c2_sha256']:
                raise AuthorizationError('C2_HASH_MISMATCH')
            with self.verifier.store.transaction() as db:
                status = self.verifier.verify(raw, _db=db, **expected)
            if status != 'VALID':
                raise AuthorizationError(status)
            return result
