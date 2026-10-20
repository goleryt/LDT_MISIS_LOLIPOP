"""Verify and extract the immutable supplier delivery; never load pickle artifacts."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ARCHIVE_SHA256 = '1afb9615c2526b21f7aa5e9dd0147b82a74777c86b7c5064b6134dcd0366573b'


def unpack(root: Path):
    archive = root / 'COMBINED_EVIDENCE_V1_1.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('COMBINED_ARCHIVE_CHECKSUM_MISMATCH')
    target = root / 'vendor'
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_ARCHIVE_PATH')
        manifest = json.loads(source.read('SHA256.json'))
        if set(names) != {*manifest, 'SHA256.json'}:
            raise ValueError('MANIFEST_FILE_SET_MISMATCH')
        for name in ('requirements-sensor-fire.txt','MODEL_STATUS.json','ENABLEMENT_POLICY.json','SHA256.json'):
            # Git may normalize line endings in text copies. Artifacts inside
            # the immutable ZIP are still verified byte for byte below.
            left=(root/name).read_text(encoding='utf8');right=source.read(name).decode('utf8')
            same=json.loads(left)==json.loads(right) if name.endswith('.json') else left.splitlines()==right.splitlines()
            if not same:
                raise ValueError('EXTERNAL_DELIVERY_COPY_MISMATCH')
        if json.loads((root/'registry.json').read_text())!=json.loads(source.read('examples/registry.json')):
            raise ValueError('REGISTRY_COPY_MISMATCH')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('UNSAFE_ARCHIVE_PATH')
            value = source.read(name)
            if name != 'SHA256.json' and hashlib.sha256(value).hexdigest() != manifest[name]:
                raise ValueError('SUPPLIER_FILE_CHECKSUM_MISMATCH')
            dest = target.joinpath(*path.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(value)
    return target


if __name__ == '__main__':
    unpack(Path(__file__).resolve().parent)
