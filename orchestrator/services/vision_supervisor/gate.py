"""Fail-closed C2 + candidate private refs validation. Public models unchanged."""
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import PurePosixPath

from pydantic import ValidationError

from orchestrator.schemas.ocr import OCRData
from orchestrator.schemas.vlm import VLMData
from .supervisor import VisionError, unique_json


def blocked():
    return VisionError(3004, 'safety evidence missing, invalid, untrusted or unbound')


@dataclass(frozen=True)
class Handoff:
    """Immutable raw-byte snapshot, not a folder to scan for the latest files."""
    identity: object
    c1: bytes
    c2: bytes
    sidecar: bytes
    c2_sha256: str


class Gate:
    @staticmethod
    def bound_c1(snapshot, identity, image_hash):
        try:
            if snapshot is None or snapshot.image_sha256 != image_hash:
                raise ValueError('C1 input hash mismatch')
            if hashlib.sha256(snapshot.documents['c1']).hexdigest() != snapshot.c1_sha256:
                raise ValueError('C1 byte hash mismatch')
            if any(getattr(snapshot.identity, k) != getattr(identity, k) for k in
                   ('job_id', 'page_id', 'generation_id', 'input_revision', 'epoch')):
                raise ValueError('C1 input revision/generation mismatch')
            model = OCRData.model_validate(unique_json(snapshot.documents['c1']))
            Gate.c1(snapshot, identity.page_id, (model.image_width, model.image_height))
            if model.status == 'failed':
                raise ValueError('Failed C1 cannot feed VLM')
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise VisionError(1002, 'C1 missing or input snapshot binding invalid') from exc

    def __init__(self, trusted_sources):
        # Must be populated by trusted M1 deployment config, never M2 request data.
        self.trusted = frozenset(trusted_sources)

    @staticmethod
    def c1(snapshot, page_id, size):
        try:
            model = OCRData.model_validate(unique_json(snapshot.documents['c1']))
            if model.page_id != page_id or (model.image_width, model.image_height) != size:
                raise ValueError('C1 page/image mismatch')
            return model
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise VisionError(1002, 'C1 violates frozen contract') from exc

    def accept(self, record, fences, c1, c2, size):
        fences.check(record)
        if type(c2.source_id) is not str or c2.source_id not in self.trusted or c2.identity != record.identity:
            raise blocked()
        try:
            raw = c2.documents['c2']
            doc = unique_json(raw)
            safety = doc.get('safety') if type(doc) is dict else None
            # Never coerce strings, numbers, null, or the internal pass_ alias here.
            if (type(safety) is not dict or type(safety.get('pass')) is not bool
                    or safety['pass'] is not True or type(safety.get('flags')) is not list
                    or any(type(flag) is not str or not flag.strip() for flag in safety['flags'])
                    or safety['flags']):
                raise blocked()
        except (ValueError, KeyError, TypeError) as exc:
            raise blocked() from exc
        try:
            model = VLMData.model_validate(doc)
            if model.page_id != record.page_id or (model.image_width, model.image_height) != size:
                raise ValueError('C2 page/image mismatch')
            self.c1(c1, record.page_id, size)
            # C1 must belong to the same job/generation/revision/epoch (OCR and
            # VLM necessarily have different attempt IDs/tokens).
            if any(getattr(c1.identity, key) != getattr(c2.identity, key) for key in
                   ('job_id', 'page_id', 'generation_id', 'input_revision', 'epoch')):
                raise ValueError('C1/C2 generation mismatch')
            digest = hashlib.sha256(raw).hexdigest()
            self.refs(c2.documents['sidecar'], c2.identity, model, digest)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise VisionError(1002, 'C2/refs violates contract or generation binding') from exc
        with fences.lock:
            fences.check(record, c2.identity)
            record.c2_sha256 = digest
        return Handoff(c2.identity, bytes(c1.documents['c1']), bytes(raw),
                       bytes(c2.documents['sidecar']), digest)

    @staticmethod
    def refs(raw, identity, c2, digest):
        refs = unique_json(raw)
        if type(refs) is not dict or refs.get('schema_version') != 'vision_refs/0.1':
            raise ValueError('Candidate refs version mismatch')
        # Frozen private contract is strict; public C1/C2 models remain unchanged.
        if set(refs) != set(asdict(identity)) | {'schema_version','c2','source','observations'}:
            raise ValueError('Unknown or missing Sidecar field')
        for key, value in asdict(identity).items():
            if type(refs.get(key)) is not type(value) or refs[key] != value:
                raise ValueError('refs identity mismatch: '+key)
        link = refs['c2']
        if (type(link) is not dict or set(link) != {'asset_id','schema_version','relative_path','sha256'}
                or link.get('schema_version') != '1.0'
                or link.get('sha256') != digest or not isinstance(link.get('asset_id'), str)
                or not link['asset_id']):
            raise ValueError('refs C2 raw-byte hash/version mismatch')
        path = link['relative_path']
        if (not isinstance(path, str) or '\\' in path or ':' in path
                or path != f'json/{identity.page_id}_vlm.json'
                or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts):
            raise ValueError('refs C2 path mismatch')
        source = refs['source']
        if (type(source) is not dict or set(source) != {'component_mode','model_ref','prompt_sha256','evidence_ref'}
                or source.get('component_mode') not in {'fixture', 'stub', 'real'}
                or not all(isinstance(source.get(k), str) and source[k]
                           for k in ('model_ref', 'prompt_sha256', 'evidence_ref'))):
            raise ValueError('Invalid source provenance')
        import re
        if not re.fullmatch('[0-9a-f]{64}', source['prompt_sha256']):
            raise ValueError('Invalid prompt fingerprint')
        observations = refs['observations']
        if type(observations) is not list:
            raise ValueError('Invalid observations')
        object_ids = {obj.object_id for obj in c2.objects}
        observed = set()
        for obs in observations:
            if type(obs) is not dict or set(obs) != {'observation_id','object_id','identity_status','visual_description','source_ref','appearance','confidence'}:
                raise ValueError('M2 must not assign cross-page identity')
            oid = obs['observation_id']
            if not isinstance(oid, str) or not oid or oid in observed:
                raise ValueError('Duplicate/invalid observation ID')
            observed.add(oid)
            if obs['object_id'] not in object_ids or obs['identity_status'] not in {'unknown', 'ambiguous'}:
                raise ValueError('Observation references foreign object/identity')
            if not all(isinstance(obs.get(k), str) and obs[k] for k in ('visual_description', 'source_ref')):
                raise ValueError('Observation missing provenance/description')
            appearance = obs['appearance']
            if (type(appearance) is not dict or set(appearance)-{'clothing', 'visible_features'}
                    or 'clothing' in appearance and (type(appearance['clothing']) is not str or not appearance['clothing'].strip())
                    or 'visible_features' in appearance and
                       (type(appearance['visible_features']) is not list or
                        not all(type(x) is str for x in appearance['visible_features']))):
                raise ValueError('Invalid visible appearance')
            confidence = obs['confidence']
            if (type(confidence) is not dict or not {'kind','calibrated'} <= set(confidence)
                    or set(confidence)-{'kind','calibrated','value'}
                    or type(confidence.get('calibrated')) is not bool):
                raise ValueError('Invalid confidence')
            # F04: no operational independent M5 calibration registry is approved.
            if confidence['calibrated']:
                raise ValueError('Unverified calibration claim')
            value = confidence.get('value')
            if confidence.get('kind') == 'unavailable':
                if value is not None or confidence['calibrated']:
                    raise ValueError('Unavailable confidence must be null and uncalibrated')
            elif (confidence.get('kind') != 'model_estimate' or type(value) not in {int, float}
                  or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError('Invalid confidence estimate')
