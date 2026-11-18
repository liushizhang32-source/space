"""M1-owned final publication fence; uses the existing Authority exclusively."""
from contextlib import contextmanager
from .billing import offline_only
from ..integration_reference.authority import require

@contextmanager
def generation_publication(session):
    consumer=session.consumer;authority=consumer.authority;attempt=session.attempt
    offline_only(authority,True)
    # Original _bound validates subject, grant, current Attempt and shared upstream.
    # Keep that same writer transaction through synchronous publication so another
    # process cannot revoke/rebind between the final check and publication.
    with consumer.fences.lock:
        with authority.tx() as db:
            service,token,row=authority._bound(db,consumer.service_token,attempt.token,dict(attempt.identity),live=False)
            require(row['state'] in {'SUBMITTED','UNKNOWN','DONE'} and row['result']==attempt.result_sha256,'UNSUBMITTED_PUBLICATION')
            consumer.fences.check(consumer.record,consumer.record.identity,_db=db) if getattr(consumer.fences,'authority',None) is authority else consumer.fences.check(consumer.record,consumer.record.identity)
            yield
            authority.event(db,'generation_published',subject=service['subject'],project=row['project'],attempt_id=row['id'],result_sha256=row['result'])
