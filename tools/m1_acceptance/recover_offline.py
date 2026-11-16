"""Trusted offline recovery CLI. No provider, credential, network or key loading."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from orchestrator.services.integration_reference.recovery import JointSnapshot
from orchestrator.services.integration_reference import Denied


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('create','verify','restore','abort'))
    parser.add_argument('--database',required=True);parser.add_argument('--anchor',required=True)
    parser.add_argument('--asset-root',required=True);parser.add_argument('--snapshot')
    parser.add_argument('--operation-id');parser.add_argument('--offline-test',action='store_true',required=True)
    parser.add_argument('--services-stopped',action='store_true')
    args=parser.parse_args()
    if args.action!='abort' and not args.snapshot:parser.error('--snapshot is required')
    if args.action in ('restore','abort') and not args.operation_id:parser.error('--operation-id is required')
    try:
        recovery=JointSnapshot(args.database,args.anchor,args.asset_root,clock=lambda:int(time.time()),offline_test=args.offline_test)
        if args.action=='create':
            result=recovery.create(args.snapshot)
            # Do not print database contents, credentials or asset bytes.
            result=dict(status='SNAPSHOT_CREATED_OFFLINE',state_sha256=result['state_sha256'],files=len(result['files']))
        elif args.action=='verify':result=recovery.verify(args.snapshot)
        elif args.action=='restore':result=recovery.restore(args.snapshot,operation_id=args.operation_id,services_stopped=args.services_stopped)
        else:result=recovery.abort(operation_id=args.operation_id,services_stopped=args.services_stopped)
    except (Denied,OSError,ValueError) as exc:
        reason=str(exc) if isinstance(exc,Denied) else 'RECOVERY_IO_OR_FORMAT_ERROR'
        print(json.dumps(dict(status='BLOCKED',reason=reason)));return 1
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
