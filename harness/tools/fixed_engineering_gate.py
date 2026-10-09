"""Verify the sole fixed software version and locked complete benchmark inputs."""
import hashlib,json,os
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(archive):
    archive=Path(archive).resolve();plan_path=archive/'control/FIXED_DESIGN.json'
    plan=json.loads(plan_path.read_text());manifest_path=archive/'control/PRODUCT_SNAPSHOT.json'
    assert plan['snapshot_sha256']==sha(manifest_path)
    manifest=json.loads(manifest_path.read_text());product=Path(manifest['product_root'])
    assert product==archive/'product' and manifest['product_baseline']['commit']==plan['product_commit']
    for row in manifest['product_baseline']['tracked_files']:
        assert sha(product/row['path'])==row['sha256'], 'Product changed: '+row['path']
    for row in plan['files']:
        assert sha(archive/row['path'])==row['sha256'], 'Locked input changed: '+row['path']
    return plan,manifest
def require(product,output,script,*,cases=None,filtered=False):
    archive=Path(os.environ['GEWU_FIXED_ARCHIVE']).resolve()
    product,output,script=map(lambda p:Path(p).resolve(),[product,output,script])
    if filtered or output.exists() or not output.is_relative_to(archive/'runs'):
        raise ValueError('A fresh complete-scope fixed-version run is required')
    plan,manifest=verify(archive)
    assert product==Path(manifest['product_root'])
    locked={r['path']:r['sha256'] for r in plan['files']}
    assert locked[str(script.relative_to(archive))]==sha(script)
    assert locked[str(Path(__file__).resolve().relative_to(archive))]==sha(__file__)
    if cases:assert locked[str(Path(cases).resolve().relative_to(archive))]==sha(cases)
    return {'phase':'fixed_version_execution','round_id':archive.name,'product_baseline':manifest['product_baseline'],'design_sha256':sha(archive/'control/FIXED_DESIGN.json'),'snapshot_sha256':sha(archive/'control/PRODUCT_SNAPSHOT.json'),'scores_authorized':False}
