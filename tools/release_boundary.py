"""Fail if withheld implementations or local-only evidence enter a distribution."""
from pathlib import Path
import tarfile,zipfile,json

root=Path(__file__).resolve().parents[1]
private=set(json.loads((root/'COMMUNITY_SCOPE.json').read_text())['excluded_modules'])
for artifact in (root/'dist').glob('*'):
    if artifact.suffix=='.whl':
        with zipfile.ZipFile(artifact) as archive:names=archive.namelist()
    elif artifact.name.endswith('.tar.gz'):
        with tarfile.open(artifact) as archive:names=archive.getnames()
    else:continue
    forbidden=[n for n in names if Path(n).stem in private or any(x in n for x in ('_tools/','wheel_site/','wheel_final_site/'))]
    assert not forbidden,(artifact,forbidden)
    assert any(n.endswith('/gb_a3.DRWDOT') for n in names),(artifact,'missing GB asset')
    print(artifact.name,'Community boundary PASS')
