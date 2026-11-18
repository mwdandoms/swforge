"""Verify the reviewed Community source and both Python distribution formats."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={'annotation_rules','process_rules','conformity','drawing_set','drawing_raster',
           'drafting','drawing_facts','blank','mechanical_review'}
PRIVATE_SIGNATURES=(b'def review_mechanical(',b'class BlankSpec',b'def arrange_projection(',
                    b'def drawing_annotations(',b'def drawing_facts(')


def digest(data):return hashlib.sha256(data).hexdigest()


def verify_source():
    manifest=json.loads((ROOT/'COMMUNITY_FILES.json').read_text(encoding='utf8'))
    files={str(p.relative_to(ROOT)).replace('\\','/'):p.read_bytes()
           for p in (ROOT/'src/swforge').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert set(files)==set(manifest['files']), 'Source file allowlist differs'
    for name,data in files.items():
        assert digest(data)==manifest['files'][name], 'Unreviewed source change: '+name
        assert PurePosixPath(name).stem not in FORBIDDEN,name
        if name.endswith('.py'):
            assert not any(signature in data for signature in PRIVATE_SIGNATURES),name
    return files


def verify_archive(path,files):
    if path.suffix=='.whl':
        with zipfile.ZipFile(path) as z:contents={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
        prefix=''
    else:
        with tarfile.open(path) as z:contents={n.name:z.extractfile(n).read() for n in z if n.isfile()}
        prefix=next(iter(contents)).split('/')[0]+'/src/'
    expected={prefix+n.removeprefix('src/'):data for n,data in files.items()}
    actual={n:v for n,v in contents.items() if n.startswith(prefix+'swforge/')}
    assert set(actual)==set(expected),(path,'Package allowlist differs',set(actual)^set(expected))
    for n,data in expected.items():assert actual[n]==data,(path,n,'Package content differs')
    assert not any(PurePosixPath(n).suffix.lower() in {'.sldprt','.sldasm','.sldlfp','.step','.stp'} for n in contents),(path,'CAD model in distribution')
    assert not any(PurePosixPath(n).stem in FORBIDDEN and n.endswith('.py') for n in contents),(path,'Withheld implementation')
    if path.suffix=='.whl':
        metadata=next(data.decode('utf8').replace('\r\n','\n') for n,data in contents.items() if n.endswith('.dist-info/METADATA'))
        assert 'Version: 2.0.0\n' in metadata
        assert '后续订阅与企业定制' in metadata
        assert '无建模历史' in metadata
    print(path.name,'PASS',len(actual),'reviewed package files')


def main():
    files=verify_source()
    artifacts=[Path(x) for x in sys.argv[1:]] or sorted((ROOT/'dist').glob('*.whl'))+sorted((ROOT/'dist').glob('*.tar.gz'))
    assert artifacts,'No distribution supplied'
    for path in artifacts:verify_archive(path,files)
    print('Community boundary PASS; no publication performed')


if __name__=='__main__':main()
