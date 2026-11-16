"""Explicit frozen-V1 offline supervisor; durable F08 admission before dispatch.

Legacy Supervisor remains for old fixture compatibility; new integration must use
this adapter with one shared Authority. No production activation or new wire keys.
"""
import uuid,os
from .supervisor import Supervisor,VisionError,Cancelled
from ..integration_reference.authority import Denied


def frozen_retryable(error,stage):
    return (stage in ('ocr','vlm') and type(error.code) is int
        and error.code in {2001,2002,2003} and error.transient is True
        and not (error.code==2001 and 'safety' in error.msg.casefold()))


class DurableSupervisor(Supervisor):
    def __init__(self,private_root,*,authority,**kwargs):
        if os.name!='nt':raise VisionError(9001,'Frozen reference requires validated Windows NTFS reader')
        super().__init__(private_root,**kwargs)
        self.authority=authority;self.owner=uuid.uuid4().hex

    @staticmethod
    def _terminal(record):
        return (record.worker_state=='reaped' and
            (not record.backend_execution or record.backend_execution['status']=='confirmed'))

    def _run(self,record,fences,stage,spec_for_attempt,image_path,*,c1=None):
        if stage not in ('ocr','vlm'):raise ValueError('Invalid stage')
        with fences.serial[record.page_id]:
            for _ in (1,2):
                fences.check(record)
                identity=fences.attempt(record)
                try:lease=self.authority.reserve_stage(identity,stage,self.owner)
                except Denied as exc:raise VisionError(9001,'Durable stage admission denied: '+str(exc)) from exc
                dispatched=False
                try:
                    spec=spec_for_attempt(lease['ordinal'])
                    fences.check(record,identity)
                    self.authority.dispatch_stage(identity,self.owner);dispatched=True
                    result=self._once(record,fences,identity,stage,spec,image_path,c1=c1)
                    self.authority.finish_stage(identity,self.owner,outcome='SUCCEEDED',terminal_confirmed=self._terminal(record))
                    if not self._terminal(record):raise VisionError(9001,'Stage terminal proof unavailable')
                    return result
                except VisionError as exc:
                    terminal=not dispatched or self._terminal(record)
                    retry=(terminal and not isinstance(exc,Cancelled) and frozen_retryable(exc,stage)
                           and not record.cancel.is_set())
                    self.authority.finish_stage(identity,self.owner,outcome='CANCELLED' if isinstance(exc,Cancelled) else 'FAILED',
                        terminal_confirmed=terminal,retry_allowed=retry)
                    fences.check(record)
                    if not retry or lease['ordinal']==2:raise
                    self.emit('backoff',identity,seconds=1,code=exc.code)
                    if record.cancel.wait(self.backoff):raise Cancelled() from exc
                except BaseException:
                    # An arbitrary post-dispatch exception is UNKNOWN, even if the
                    # local worker happened to exit; never infer billing/remote drain.
                    self.authority.finish_stage(identity,self.owner,outcome='FAILED',
                        terminal_confirmed=not dispatched,retry_allowed=False)
                    raise
            raise AssertionError('Unreachable')
