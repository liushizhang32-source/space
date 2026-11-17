"""Trusted offline Gate bridge, with final shared-current CAS when configured."""
from dataclasses import asdict
import hashlib
from ..vision_supervisor.gate import Gate
from .authority import require


def begin_from_gate(authority,gate,record,fences,c1,c2,size,*,service,project,request_id,amount,image=None,final_messages=None):
    require(type(gate) is Gate,'UNTRUSTED_GATE')
    shared=getattr(fences,'authority',None)
    require(shared is None or shared is authority,'AUTHORITY_MISMATCH')
    with fences.lock:
        # Gate checks SharedFences through its own short reads; never recursively
        # acquire a second SQLite writer while this bridge owns the write lock.
        with authority.tx() as db:
            subject=authority._token(db,service,'service')['subject']
            authority._grant(db,subject,project,'generate');authority._grant(db,subject,project,'assets.read')
        handoff=gate.accept(record,fences,c1,c2,size)
        if shared is not None or image is not None:
            require(type(image) is bytes and image and hashlib.sha256(image).hexdigest()==c1.image_sha256==c2.image_sha256,'IMAGE_BINDING')
        lineage={k:v for k,v in asdict(handoff.identity).items() if k not in ('attempt_id','fencing_token')}
        prefix='upstream/'+handoff.identity.generation_id+'/'+handoff.identity.attempt_id
        assets={prefix+'/c1.json':handoff.c1,prefix+'/c2.json':handoff.c2,prefix+'/sidecar.json':handoff.sidecar}
        if image is not None:assets[prefix+'/image.bin']=image
        with authority.tx() as db:
            subject=authority._token(db,service,'service')['subject']
            authority._grant(db,subject,project,'generate');authority._grant(db,subject,project,'assets.read')
            if shared is not None:fences.check(record,handoff.identity,_db=db)
            for name,raw in assets.items():authority.put_asset(project,name,raw,_db=db)
            return authority.begin(service,project,record.page_id,request_id,amount,list(assets),lineage=lineage,_db=db,
                                   upstream_identity=handoff.identity if shared is not None else None,final_messages=final_messages)
