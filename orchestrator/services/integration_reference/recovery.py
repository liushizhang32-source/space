"""Offline joint DB/bundle recovery. Never resets or imports a checkpoint anchor.

Restore is an explicit trusted-operator operation at the original authority path.
Maintenance blocks both existing and newly opened Authority clients. Previous asset
roots are quarantined by rename, never deleted. No production keys/resources involved.
"""
from pathlib import Path
import hashlib,json,os,re,sqlite3,tempfile,uuid
from contextlib import contextmanager
from functools import wraps
from .authority import Authority,Denied,require,canonical
from .files import WindowsAssetReader
from ..vision_supervisor.supervisor import unique_json,VisionError
from ..vision_supervisor.pipeline import AtomicStore

FORMAT='m1-offline-joint-snapshot/0.1'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
HEX=re.compile(r'[0-9a-f]{64}')


def serialized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self._exclusive():return method(self,*args,**kwargs)
    return call


def write_new(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


class CheckpointSource:
    """Read-only checkpoint adapter: backup operators never load signing keys."""
    _state=staticmethod(Authority._state)
    _check_owner_path=Authority._check_owner_path
    snapshot_guard=Authority.snapshot_guard
    _backup_locked=Authority._backup_locked
    def __init__(self,path,anchor,clock):self.path,self.anchor,self.clock=path,anchor,clock
    @property
    def maintenance_path(self):return Path(str(self.path)+'.maintenance')


class JointSnapshot:
    def __init__(self,database,retained_anchor,asset_root,*,clock,offline_test=False):
        require(offline_test is True,'PRODUCTION_BLOCKED')
        require(os.name=='nt','FILE_PLATFORM_UNSUPPORTED')
        self.path=Path(database).resolve();self.anchor=Path(retained_anchor).resolve()
        self.asset_root=Path(os.path.abspath(asset_root));self.clock=clock
        self.authority=CheckpointSource(self.path,self.anchor,clock)
        require(self.path!=self.anchor and bool(self.asset_root.name)
                and not self.path.is_relative_to(self.asset_root) and not self.anchor.is_relative_to(self.asset_root),'RECOVERY_PATHS')
        self.max_bytes=256*1024*1024

    @classmethod
    def for_store(cls,authority,store):
        require(getattr(store.fences,'authority',None) is authority,'SHARED_AUTHORITY_REQUIRED')
        obj=cls(authority.path,authority.anchor,store.root,clock=authority.clock,offline_test=True)
        obj.authority=authority;return obj

    @property
    def maintenance_path(self):return Path(str(self.path)+'.maintenance')

    def _checkpoint(self):
        value=self.anchor.read_text(encoding='ascii')
        require(HEX.fullmatch(value),'CHECKPOINT_INVALID')
        return value

    @staticmethod
    def _published_files(db,reader,prefix='',maximum=256*1024*1024):
        files={};total=0
        for row in db.execute("SELECT * FROM vision_current WHERE status='DONE' ORDER BY page_id"):
            page=row['page_id'];AtomicStore.safe_page(page)
            pointer='pointers/'+page+'.json';raw=reader.read_bytes(prefix+pointer);doc=unique_json(raw)
            require(type(doc) is dict and set(doc)=={'identity','bundle','c2_sha256','sha256'},'MANIFEST_INVALID')
            require(sha(canonical(doc))==row['manifest_sha256'] and canonical(doc['identity'])==canonical(json.loads(row['identity'])),'MANIFEST_UNAUTHORIZED')
            require(type(doc['bundle']) is str and re.fullmatch(r'[a-zA-Z0-9_-]+',doc['bundle']),'MANIFEST_PATH')
            hashes=doc['sha256'];require(type(hashes) is dict and 0<len(hashes)<=10000,'MANIFEST_INVALID')
            require(hashes.get(f'json/{page}_vlm.json')==doc['c2_sha256'],'MANIFEST_C2')
            total+=len(raw);require(total<=maximum,'SNAPSHOT_TOO_LARGE')
            files[pointer]=raw
            for name,digest in hashes.items():
                WindowsAssetReader._components(name)
                require(type(digest) is str and HEX.fullmatch(digest),'MANIFEST_HASH')
                relative='bundles/'+doc['bundle']+'/'+name;content=reader.read_bytes(prefix+relative)
                require(sha(content)==digest,'BUNDLE_INTEGRITY')
                require(relative not in files or files[relative]==content,'SNAPSHOT_COLLISION')
                if relative not in files:total+=len(content)
                require(total<=maximum,'SNAPSHOT_TOO_LARGE')
                files[relative]=content
        return files

    @serialized
    def create(self,target,*,fault=lambda phase:None):
        require(self.authority is not None,'HEALTHY_SOURCE_REQUIRED')
        self._journal_read()
        target=Path(os.path.abspath(target));require(not target.exists(),'SNAPSHOT_EXISTS')
        # A new snapshot must not be a child of the asset root it is capturing.
        require(not target.is_relative_to(self.asset_root),'SNAPSHOT_PATH')
        target.mkdir(parents=True);write_new(target/'snapshot.incomplete',b'INCOMPLETE')
        with self.authority.snapshot_guard() as (db,state):
            reader=WindowsAssetReader(self.asset_root,max_bytes=64*1024*1024)
            files=self._published_files(db,reader,maximum=self.max_bytes)
            total=sum(len(raw) for raw in files.values())
            require(total<=self.max_bytes,'SNAPSHOT_TOO_LARGE')
            db_hash=self.authority._backup_locked(target/'authority.sqlite',state)
            db_size=(target/'authority.sqlite').stat().st_size
            require(db_size<=64*1024*1024 and total+db_size<=self.max_bytes,'SNAPSHOT_TOO_LARGE')
            fault('database_copied')
            for name,raw in files.items():
                write_new(target/'files'/name,raw);fault('file_copied:'+name)
            manifest=dict(format=FORMAT,state_sha256=state,db_sha256=db_hash,database_path=str(self.path),
                asset_root=str(self.asset_root),files={n:sha(v) for n,v in files.items()},total_bytes=total+db_size)
            fault('before_complete')
            write_new(target/'snapshot.json',canonical(manifest))
            (target/'snapshot.incomplete').unlink()
            self._journal('SNAPSHOT_CREATED',sha(canonical(manifest)),state_sha256=state)
        return manifest

    def _inspect(self,snapshot):
        try:return self._inspect_untrusted(snapshot)
        except Denied:raise
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,VisionError):
            raise Denied('SNAPSHOT_INVALID') from None

    def _inspect_untrusted(self,snapshot):
        require(not (Path(snapshot)/'snapshot.incomplete').exists(),'SNAPSHOT_INCOMPLETE')
        reader=WindowsAssetReader(snapshot,max_bytes=64*1024*1024)
        raw_manifest=reader.read_bytes('snapshot.json');require(len(raw_manifest)<=4*1024*1024,'SNAPSHOT_TOO_LARGE')
        doc=unique_json(raw_manifest)
        require(type(doc) is dict and set(doc)=={'format','state_sha256','db_sha256','database_path','asset_root','files','total_bytes'}
                and doc['format']==FORMAT,'SNAPSHOT_FORMAT')
        require(Path(doc['database_path'])==self.path and Path(doc['asset_root'])==self.asset_root,'SNAPSHOT_PATH_MISMATCH')
        require(doc['state_sha256']==self._checkpoint(),'SNAPSHOT_ROLLBACK')
        require(type(doc['files']) is dict and len(doc['files'])<=10000,'SNAPSHOT_FORMAT')
        raw_db=reader.read_bytes('authority.sqlite');require(sha(raw_db)==doc['db_sha256'],'SNAPSHOT_DB_HASH')
        # SQLite sees an owned immutable copy of the exact bytes just verified,
        # never a second untrusted pathname open after validation.
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='m1-snapshot-inspect-',dir=self.path.parent) as folder:
            temp=Path(folder)/'inspect.sqlite';write_new(temp,raw_db)
            db=sqlite3.connect(temp.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA query_only=ON')
                require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','SNAPSHOT_DB_CORRUPT')
                require(Authority._state(db)==doc['state_sha256'],'SNAPSHOT_STATE')
                require(db.execute('SELECT bound_path FROM meta WHERE id=1').fetchone()[0]==str(self.path),'AUTHORITY_PATH_MISMATCH')
                require(type(self.clock()) is int and self.clock()>=db.execute('SELECT time FROM meta').fetchone()[0],'CLOCK_ROLLBACK')
                files=self._published_files(db,reader,'files/',maximum=self.max_bytes-len(raw_db))
            finally:db.close()
        require({n:sha(v) for n,v in files.items()}==doc['files'],'SNAPSHOT_CATALOGUE')
        total=len(raw_db)+sum(len(v) for v in files.values())
        require(type(doc['total_bytes']) is int and total==doc['total_bytes'] and total<=self.max_bytes,'SNAPSHOT_TOO_LARGE')
        return doc,raw_db,files,sha(canonical(doc))

    def verify(self,snapshot):
        doc,raw_db,files,fingerprint=self._inspect(snapshot)
        return dict(state_sha256=doc['state_sha256'],files=len(files),snapshot_sha256=fingerprint)

    @serialized
    def restore(self,snapshot,*,operation_id,services_stopped=False,fault=lambda phase:None):
        require(services_stopped is True,'OFFLINE_RESTORE_REQUIRES_STOP')
        require(type(operation_id) is str and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',operation_id),'RESTORE_OPERATION')
        doc,raw_db,files,fingerprint=self._inspect(snapshot)
        records=self._journal_read()
        completed=any(r['payload'].get('action')=='RESTORE_COMPLETED' and r['payload'].get('operation_id')==operation_id
                      and r['payload'].get('snapshot_sha256')==fingerprint for r in records)
        if completed and self._installed_matches(doc):
            if self.maintenance_path.exists():
                require(self._pending_marker().get('operation_id')==operation_id,'RESTORE_OWNER_MISMATCH')
                self.maintenance_path.unlink()
            return dict(status='RESTORED_OFFLINE',state_sha256=doc['state_sha256'],files=len(files))
        marker=dict(format=FORMAT,operation_id=operation_id,state_sha256=doc['state_sha256'],snapshot_sha256=fingerprint)
        if self.maintenance_path.exists():
            require(self._pending_marker()==marker,'RESTORE_OWNER_MISMATCH')
        else:write_new(self.maintenance_path,canonical(marker))
        self._journal('RESTORE_STARTED',operation_id,snapshot_sha256=fingerprint,state_sha256=doc['state_sha256'])
        # All Authority entry points check the marker again after taking SQLite's
        # writer lock. An already admitted writer is drained before replacement.
        guard=None
        if self.path.exists():
            try:
                guard=sqlite3.connect(self.path,timeout=10,isolation_level=None)
                guard.execute('BEGIN IMMEDIATE')
            except sqlite3.DatabaseError:
                if guard is not None:guard.close();guard=None
                # Corrupt/missing DB is recoverable only under the explicit stopped
                # operator contract plus the retained, independently trusted anchor.
        try:
            require(self._checkpoint()==doc['state_sha256'],'SNAPSHOT_ROLLBACK')
            self._journal('RESTORE_PHASE',operation_id,phase='maintenance_ready')
            fault('maintenance_ready')
        finally:
            if guard is not None:
                if guard.in_transaction:guard.rollback()
                guard.close()
        # No new authority transaction can enter until the marker is removed.
        self.asset_root.parent.mkdir(parents=True,exist_ok=True)
        parent=self.asset_root.parent.resolve()
        require(parent==self.asset_root.parent,'RESTORE_PARENT_REPARSE')
        staging=Path(tempfile.mkdtemp(prefix='.m1-restore-assets-',dir=parent)).resolve()
        require(staging.parent==parent,'RESTORE_PATH')
        for relative,raw in files.items():
            write_new(staging/relative,raw)
        self._journal('RESTORE_PHASE',operation_id,phase='files_staged')
        fault('files_staged')
        if self.asset_root.exists():
            # Refuse a reparse root. Keep every original root as a reversible
            # quarantine instead of recursively deleting old data or unknown files.
            with WindowsAssetReader._open(self.asset_root,directory=True):pass
            quarantine=self.asset_root.with_name(self.asset_root.name+'.before-restore-'+operation_id+'-'+uuid.uuid4().hex)
            require(quarantine.parent==parent and not quarantine.exists(),'RESTORE_PATH')
            os.replace(self.asset_root,quarantine)
        self._journal('RESTORE_PHASE',operation_id,phase='old_assets_quarantined')
        fault('old_assets_quarantined')
        require(staging.parent==self.asset_root.parent,'RESTORE_PATH')
        os.replace(staging,self.asset_root)
        self._journal('RESTORE_PHASE',operation_id,phase='assets_installed');fault('assets_installed')
        temp_db=self.path.with_name(self.path.name+'.restore-'+operation_id+'-'+uuid.uuid4().hex+'.tmp')
        require(temp_db.parent==self.path.parent,'RESTORE_PATH');write_new(temp_db,raw_db)
        os.replace(temp_db,self.path)
        self._journal('RESTORE_PHASE',operation_id,phase='database_installed');fault('database_installed')
        require(self._checkpoint()==doc['state_sha256'],'SNAPSHOT_ROLLBACK')
        # Validate the installed state/files while all service operations remain gated.
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            require(Authority._state(db)==doc['state_sha256'],'RESTORE_STATE')
            installed=self._published_files(db,WindowsAssetReader(self.asset_root,max_bytes=64*1024*1024))
            require({n:sha(v) for n,v in installed.items()}==doc['files'],'RESTORE_FILES')
        finally:db.close()
        fault('before_release')
        require(self._checkpoint()==doc['state_sha256'],'SNAPSHOT_ROLLBACK')
        self._journal('RESTORE_COMPLETED',operation_id,snapshot_sha256=fingerprint,state_sha256=doc['state_sha256'])
        fault('completion_recorded')
        self.maintenance_path.unlink()
        return dict(status='RESTORED_OFFLINE',state_sha256=doc['state_sha256'],files=len(files))


    @property
    def journal_path(self):return Path(str(self.anchor)+'.recovery.jsonl')

    @contextmanager
    def _exclusive(self):
        import msvcrt
        self.path.parent.mkdir(parents=True,exist_ok=True)
        lock=Path(str(self.maintenance_path)+'.lock')
        with lock.open('a+b') as stream:
            if stream.tell()==0:stream.write(b'0');stream.flush()
            stream.seek(0)
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise Denied('RECOVERY_BUSY') from None
            try:yield
            finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

    def _journal_read(self):
        if not self.journal_path.exists():return []
        records=[];previous=''
        try:
            for line in self.journal_path.read_bytes().splitlines():
                row=unique_json(line)
                require(type(row) is dict and set(row)=={'seq','previous','payload','hash'},'RECOVERY_AUDIT_CORRUPT')
                body={k:row[k] for k in ('seq','previous','payload')}
                require(row['seq']==len(records)+1 and row['previous']==previous and sha(canonical(body))==row['hash'],'RECOVERY_AUDIT_CORRUPT')
                previous=row['hash'];records.append(row)
        except Denied:raise
        except (ValueError,TypeError,KeyError):raise Denied('RECOVERY_AUDIT_CORRUPT') from None
        return records

    def _journal(self,action,operation_id,**values):
        records=self._journal_read()
        body=dict(seq=len(records)+1,previous=records[-1]['hash'] if records else '',
                  payload=dict(action=action,operation_id=operation_id,at=self.clock(),**values))
        row={**body,'hash':sha(canonical(body))}
        with self.journal_path.open('ab') as stream:
            stream.write(canonical(row)+b'\n');stream.flush();os.fsync(stream.fileno())

    def _installed_matches(self,doc):
        if not self.path.is_file():return False
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':return False
            if Authority._state(db)!=doc['state_sha256'] or self._checkpoint()!=doc['state_sha256']:return False
            files=self._published_files(db,WindowsAssetReader(self.asset_root,max_bytes=64*1024*1024),maximum=self.max_bytes)
            return {n:sha(v) for n,v in files.items()}==doc['files']
        except (Denied,OSError,sqlite3.Error,ValueError,VisionError):return False
        finally:
            if db.in_transaction:db.rollback()
            db.close()

    @serialized
    def abort(self,*,operation_id,services_stopped=False):
        """Release a gate only when live DB and files still match the retained head."""
        require(services_stopped is True,'OFFLINE_RESTORE_REQUIRES_STOP')
        require(self.maintenance_path.is_file(),'RESTORE_NOT_PENDING')
        marker=self._pending_marker()
        require(marker.get('operation_id')==operation_id,'RESTORE_OWNER_MISMATCH')
        self._journal_read()
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok' and Authority._state(db)==self._checkpoint(),'RESTORE_LIVE_STATE_INVALID')
            require(db.execute('SELECT bound_path FROM meta').fetchone()[0]==str(self.path),'AUTHORITY_PATH_MISMATCH')
            self._published_files(db,WindowsAssetReader(self.asset_root,max_bytes=64*1024*1024),maximum=self.max_bytes)
            self._journal('RESTORE_ABORTED',operation_id,state_sha256=self._checkpoint())
            self.maintenance_path.unlink()
        finally:
            if db.in_transaction:db.rollback()
            db.close()
        return dict(status='ABORTED_WITH_VALID_LIVE_STATE')


    def _pending_marker(self):
        try:
            value=unique_json(self.maintenance_path.read_bytes())
            require(type(value) is dict and set(value)=={'format','operation_id','state_sha256','snapshot_sha256'}
                    and value['format']==FORMAT and type(value['operation_id']) is str
                    and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',value['operation_id'])
                    and type(value['state_sha256']) is str and HEX.fullmatch(value['state_sha256'])
                    and type(value['snapshot_sha256']) is str and HEX.fullmatch(value['snapshot_sha256']),'RESTORE_MARKER_INVALID')
            return value
        except Denied:raise
        except (OSError,ValueError,TypeError,KeyError):raise Denied('RESTORE_MARKER_INVALID') from None
