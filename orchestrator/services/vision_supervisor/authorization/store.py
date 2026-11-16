"""SQLite atomic candidate ledger. Only M1 trusted lifecycle code may mutate current.

This separate database does NOT make the existing in-memory Fences durable.
Production needs a transactional lifecycle integration before enabling issuance.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sqlite3
from .exceptions import AuthorizationError

_OWNED_TRANSACTIONS = ContextVar('gate_authorization_transactions', default=())


class Store:
    def __init__(self, path):
        if str(path) == ':memory:':
            raise AuthorizationError('BLOCKED')
        self.path = str(Path(path).resolve())
        with self.transaction() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS current_asset (
              page_id TEXT PRIMARY KEY, identity TEXT NOT NULL,
              c2_sha256 TEXT NOT NULL, enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS authorization (
              authorization_id TEXT PRIMARY KEY, jti TEXT UNIQUE NOT NULL,
              nonce TEXT UNIQUE NOT NULL, request_id TEXT UNIQUE NOT NULL,
              binding TEXT NOT NULL, credential TEXT NOT NULL, identity TEXT NOT NULL,
              c2_sha256 TEXT NOT NULL, audience TEXT NOT NULL, scope TEXT NOT NULL,
              key_id TEXT NOT NULL, issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVOKED','EXPIRED')),
              revoked_at INTEGER, revocation_reason TEXT);
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY, authorization_id TEXT NOT NULL,
              action TEXT NOT NULL, at INTEGER NOT NULL, reason TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS audit_once ON audit(authorization_id,action);
            CREATE TABLE IF NOT EXISTS gate_decision (
              gate_decision_id TEXT PRIMARY KEY, identity TEXT NOT NULL,
              c1_sha256 TEXT NOT NULL, c2_sha256 TEXT NOT NULL, sidecar_sha256 TEXT NOT NULL,
              decision TEXT NOT NULL CHECK(decision IN ('PASS','DENY')),
              decided_at INTEGER NOT NULL, policy_version TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS authorization_decision (
              authorization_id TEXT PRIMARY KEY REFERENCES authorization(authorization_id),
              gate_decision_id TEXT NOT NULL REFERENCES gate_decision(gate_decision_id));
            CREATE TABLE IF NOT EXISTS gate_evidence (
              gate_decision_id TEXT PRIMARY KEY REFERENCES gate_decision(gate_decision_id) ON DELETE CASCADE,
              c1_identity TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS gate_event (
              event_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN
                ('CURRENT_DENY','STALE_EVIDENCE','SUPERSEDED','INTERNAL_ERROR')),
              gate_decision_id TEXT REFERENCES gate_decision(gate_decision_id),
              authorization_id TEXT, evidence_identity TEXT NOT NULL,
              at INTEGER NOT NULL, reason TEXT NOT NULL);
            ''')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise AuthorizationError('BLOCKED')

    def require_transaction_owner(self):
        # A Reader may not commit its caller's write or open a competing writer.
        # All Store instances on this thread/context share canonical-path ownership.
        if os.path.normcase(self.path) in _OWNED_TRANSACTIONS.get():
            raise AuthorizationError('BLOCKED')

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5, isolation_level=None)

    @contextmanager
    def transaction(self):
        self.require_transaction_owner()
        token = _OWNED_TRANSACTIONS.set((*_OWNED_TRANSACTIONS.get(), os.path.normcase(self.path)))
        db = None
        try:
            db = self._connect()
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.Error as exc:
            if db is not None:
                db.rollback()
            raise AuthorizationError('BLOCKED') from exc
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            try:
                if db is not None:
                    db.close()
            finally:
                _OWNED_TRANSACTIONS.reset(token)

    def set_current_for_offline_adapter(self, identity, c2_sha256, *, enabled=True):
        """Trusted FAKE lifecycle hook, never reachable through an HTTP request.

        Real deployment must replace this hook with its authoritative transaction.
        """
        from dataclasses import asdict
        with self.transaction() as db:
            db.execute('INSERT OR REPLACE INTO current_asset VALUES (?,?,?,?)',
                       (identity.page_id, json.dumps(asdict(identity)), c2_sha256, int(enabled)))

    def deny_current(self, authorization_id, expected_identity, expected_c2_sha256, now,
                     *, _db, reason='Current Gate rejected'):
        """CAS exactly one captured authorization, never a replacement or blanket row.

        Caller owns the transaction and commits the matching decision/event with it.
        Latest ACTIVE authorization per audience/scope is resolved from M1's ledger,
        not a worker-supplied ID. Unknown state never counts as CURRENT_DENY.
        """
        from dataclasses import asdict
        db = _db
        current = db.execute('SELECT * FROM current_asset WHERE page_id=?', (expected_identity.page_id,)).fetchone()
        target = db.execute('SELECT rowid AS serial,* FROM authorization WHERE authorization_id=?', (authorization_id,)).fetchone()
        if (current is None or not current['enabled'] or target is None
                or json.loads(current['identity']) != asdict(expected_identity)
                or json.loads(target['identity']) != asdict(expected_identity)
                or current['c2_sha256'] != expected_c2_sha256 or target['c2_sha256'] != expected_c2_sha256):
            return False
        changed = db.execute('''UPDATE authorization SET status='REVOKED',revoked_at=?,revocation_reason=?
            WHERE authorization_id=? AND identity=? AND c2_sha256=? AND status='ACTIVE'
            AND EXISTS(SELECT 1 FROM current_asset WHERE page_id=? AND identity=? AND c2_sha256=? AND enabled=1)
            AND NOT EXISTS(SELECT 1 FROM authorization newer WHERE newer.rowid>?
              AND newer.identity=? AND newer.c2_sha256=? AND newer.audience=? AND newer.scope=? AND newer.status='ACTIVE')''',
            (now,reason,authorization_id,target['identity'],expected_c2_sha256,
             expected_identity.page_id,current['identity'],expected_c2_sha256,target['serial'],
             target['identity'],expected_c2_sha256,target['audience'],target['scope'])).rowcount
        if changed != 1:
            return False
        disabled = db.execute('''UPDATE current_asset SET enabled=0
            WHERE page_id=? AND identity=? AND c2_sha256=? AND enabled=1''',
            (expected_identity.page_id,current['identity'],expected_c2_sha256)).rowcount
        if disabled != 1:
            raise AuthorizationError('BLOCKED')
        db.execute('INSERT INTO audit(authorization_id,action,at,reason) VALUES (?,?,?,?)',
                   (authorization_id,'REVOKED',now,reason))
        return True

    @staticmethod
    def expire(db, jti, now):
        row = db.execute('SELECT authorization_id,status FROM authorization WHERE jti=?', (jti,)).fetchone()
        if row and row['status'] == 'ACTIVE':
            db.execute("UPDATE authorization SET status='EXPIRED' WHERE jti=?", (jti,))
            db.execute('INSERT INTO audit(authorization_id,action,at,reason) VALUES (?,?,?,?)',
                       (row['authorization_id'],'EXPIRED',now,'Credential lifetime elapsed'))

    def expire_due(self, now):
        """Observed expiry commits independently of a rejected issuance request."""
        with self.transaction() as db:
            for row in db.execute("SELECT jti FROM authorization WHERE status='ACTIVE' AND expires_at<=?",(now,)).fetchall():
                self.expire(db,row['jti'],now)

    def transition_for_offline_test(self, previous, identity, digest, *, enabled=True, now):
        """CAS test fixture, NOT a production lifecycle adapter.

        Real Jobs/Fences have no durable shared transaction; production is BLOCKED.
        Kept separate from the unchanged V0.1 fixture for regression compatibility.
        """
        from dataclasses import asdict
        with self.transaction() as db:
            row = db.execute('SELECT * FROM current_asset WHERE page_id=?', (previous.page_id,)).fetchone()
            if row is None or json.loads(row['identity']) != asdict(previous):
                raise AuthorizationError('STALE_GENERATION')
            if identity.page_id != previous.page_id:
                raise AuthorizationError('IDENTITY_MISMATCH')
            # Compatibility fixture only: lifecycle invalidation is distinct from
            # one authorization's CURRENT_DENY. Every update still targets an ID.
            for auth in db.execute("SELECT * FROM authorization WHERE status='ACTIVE'").fetchall():
                if json.loads(auth['identity']) != asdict(previous):
                    continue
                changed = db.execute("UPDATE authorization SET status='REVOKED',revoked_at=?,revocation_reason=? WHERE authorization_id=? AND identity=? AND c2_sha256=? AND status='ACTIVE'",
                    (now,'Offline lifecycle transition',auth['authorization_id'],auth['identity'],auth['c2_sha256'])).rowcount
                if changed != 1:
                    raise AuthorizationError('BLOCKED')
                db.execute('INSERT INTO audit(authorization_id,action,at,reason) VALUES (?,?,?,?)',
                           (auth['authorization_id'],'REVOKED',now,'Offline lifecycle transition'))
            db.execute('UPDATE current_asset SET identity=?,c2_sha256=?,enabled=? WHERE page_id=?',
                       (json.dumps(asdict(identity)),digest,int(enabled),identity.page_id))

    @staticmethod
    def check_decision(db, payload, *, require_link=True):
        from dataclasses import asdict
        row = db.execute('SELECT * FROM gate_decision WHERE gate_decision_id=?',
                         (payload.gate_decision_id,)).fetchone()
        if (row is None or row['decision'] != 'PASS' or
                row['policy_version'] != 'gate.accept/0.1.1' or
                json.loads(row['identity']) != asdict(payload.identity) or
                row['c2_sha256'] != payload.c2_sha256):
            raise AuthorizationError('INVALID_DECISION')
        if require_link:
            link = db.execute('SELECT gate_decision_id FROM authorization_decision WHERE authorization_id=?',
                              (payload.authorization_id,)).fetchone()
            if link is None or link[0] != payload.gate_decision_id:
                raise AuthorizationError('INVALID_DECISION')

    @staticmethod
    def check_current(db, identity, digest):
        from dataclasses import asdict
        current = db.execute('SELECT * FROM current_asset WHERE page_id=?',
                             (identity.page_id,)).fetchone()
        if current is None or not current['enabled']:
            raise AuthorizationError('BLOCKED')
        old, new = asdict(identity), json.loads(current['identity'])
        if (type(new) is not dict or set(new) != set(old)
                or any(type(new[k]) is not type(v) for k,v in old.items())):
            raise AuthorizationError('BLOCKED')
        if any(old[k] != new[k] for k in ('job_id','page_id','generation_id','input_revision','epoch')):
            raise AuthorizationError('STALE_GENERATION')
        if any(old[k] != new[k] for k in ('attempt_id','fencing_token')):
            raise AuthorizationError('FENCING_MISMATCH')
        if digest != current['c2_sha256']:
            raise AuthorizationError('C2_HASH_MISMATCH')
