"""Read-only archive integrity check; does not start a model or simulator."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def verify():
    files = [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts]
    videos = {p.relative_to(ROOT).as_posix() for p in files if p.suffix == '.mp4'}
    manifest = json.loads((ROOT / 'media/manifest.json').read_text())
    assert manifest['video_count'] == len(manifest['videos']) == 4
    assert videos == {x['path'] for x in manifest['videos']}, 'Unexpected or missing video'
    for item in manifest['videos']:
        p = ROOT / item['path']
        assert p.stat().st_size == item['bytes'], item['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256'], item['path']

    frozen_count = 0
    for name in ['20260928-isolated-visual-eval01', '20260928-isolated-four-view-resume01']:
        run = ROOT / 'runs' / name
        protocol = json.loads((run / 'protocol.json').read_text())
        for path, digest in protocol['frozen_files'].items():
            assert hashlib.sha256((run / path).read_bytes()).hexdigest() == digest, (name, path)
            frozen_count += 1

    patterns = [
        re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})'),
        re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----'),
        re.compile(rb'"(?:access_token|refresh_token|id_token|api_key)"\s*:\s*"[^"\n]{12,}"'),
        re.compile(rb'https?://[^/\s:@]+:[^/\s@]+@'),
    ]
    python_count = 0
    text_count = 0
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        assert not p.is_symlink(), rel
        assert p.name not in {'access.token', 'auth.json', '.env'}, rel
        assert p.suffix not in {'.pem', '.key', '.pid', '.lock', '.pyc'}, rel
        assert p.stat().st_size < 100 * 1024 * 1024, rel
        if p.suffix in {'.mp4', '.jpg', '.png', '.pkl'}:
            continue
        data = p.read_bytes()
        assert not any(rx.search(data) for rx in patterns), 'Review possible credential in ' + rel
        text_count += 1
        if p.suffix == '.py':
            ast.parse(data, filename=rel)
            python_count += 1

    result = json.loads((ROOT / 'runs/20260928-isolated-four-view-resume01/result.json').read_text())
    assert result['success'] and result['verification']['successful_checks'] == 500
    assert result['phase_action_count'] == 12 and result['agent_decisions'] == 10
    print(json.dumps({'passed': True, 'video_count': len(videos),
                      'video_bytes': sum(x['bytes'] for x in manifest['videos']),
                      'frozen_files_verified': frozen_count, 'python_files_parsed': python_count,
                      'text_files_scanned': text_count, 'files_checked': len(files)}, indent=2))


if __name__ == '__main__':
    verify()
