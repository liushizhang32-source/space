from .exceptions import AuthorizationError


def revoke(store, authorization_id, *, at, reason):
    if type(reason) is not str or not reason.strip() or type(at) is not int:
        raise AuthorizationError('MALFORMED')
    with store.transaction() as db:
        row = db.execute('SELECT status FROM authorization WHERE authorization_id=?',
                         (authorization_id,)).fetchone()
        if row is None:
            raise AuthorizationError('UNKNOWN_JTI')
        if row['status'] == 'REVOKED':
            return
        db.execute("UPDATE authorization SET status='REVOKED', revoked_at=?, revocation_reason=? WHERE authorization_id=?",
                   (at, reason, authorization_id))
        db.execute('INSERT INTO audit(authorization_id,action,at,reason) VALUES (?,?,?,?)',
                   (authorization_id,'REVOKED',at,reason))
