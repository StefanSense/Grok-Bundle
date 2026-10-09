#!/usr/bin/env python3
"""Independent validator for the split Grok edition (does not import the build script).

  python tools/validate_dist.py <original Stefan_Sense_Bundle_Grok.zip> <dist dir>

Checks every .skill and .md file the way an importer and an agent would meet them:
  * archive hygiene: one top folder named like the skill, SKILL.md inside it, safe ASCII paths,
    no duplicates, no symlinks, no __pycache__, size;
  * SKILL.md / .md frontmatter parsed with a real YAML parser against the Agent Skills limits
    (name: lowercase letters, digits and single hyphens, <= 64 chars, equals the folder name;
    description: non-empty, <= 1024 chars, no angle brackets; no extra keys);
  * every path a skill tells the agent to open (`core/...`, `library/...`, `scripts/...`) exists,
    and every relative link inside library INSTRUCTIONS.md resolves;
  * library files are byte-identical to the original library.zip (RUNTIME.md excepted, by design);
  * core workflow text is complete inside SKILL.md and the .md edition;
  * all 32 core and 586 library workflows are placed in at least one skill;
  * the skill's own `sense.py check` and `selftest` pass after extraction (run as subprocesses).
"""
import hashlib, io, json, re, subprocess, sys, tempfile, zipfile
from pathlib import Path, PurePosixPath

import yaml

NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
ALLOWED_KEYS = {'name', 'description'}
PATH_RE = re.compile(r'`((?:core|library|scripts)/[^`\s<>…*]+)`')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def frontmatter(text, where, problems):
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not m:
        problems.append(where + ': no YAML frontmatter at the very start'); return {}
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        problems.append(where + ': YAML error ' + str(e)); return {}
    if not isinstance(meta, dict):
        problems.append(where + ': frontmatter is not a mapping'); return {}
    if set(meta) - ALLOWED_KEYS: problems.append(where + ': extra keys ' + str(sorted(set(meta) - ALLOWED_KEYS)))
    name, desc = meta.get('name'), meta.get('description')
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
        problems.append(where + ': invalid name %r' % name)
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024 or '<' in desc or '>' in desc:
        problems.append(where + ': invalid description (len %s)' % (len(desc) if isinstance(desc, str) else None))
    return meta


def load_original(path):
    with zipfile.ZipFile(path) as z:
        prefix = next(n[:-len('SKILL.md')] for n in z.namelist() if n.endswith('/SKILL.md') and n.count('/') == 1)
        files = {i.filename[len(prefix):]: z.read(i) for i in z.infolist() if not i.is_dir()}
    with zipfile.ZipFile(io.BytesIO(files['library/library.zip'])) as z:
        lib = {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}
    catalog = json.loads(files['library/catalog.json'])
    core = sorted({n.split('/')[1] for n in files if n.startswith('core/') and n.endswith('/WORKFLOW.md')})
    return files, lib, catalog, core


def core_body_lines(text):
    """Content lines of a core WORKFLOW.md that must survive inlining (headings and paths are rewritten)."""
    body = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith('#') or 'references/' in s or 'assets/' in s or 'bundle root' in s or 'корня бандла' in s:
            continue
        out.append(s)
    return out


def check_skill(path, original, problems, placed):
    files, lib, catalog, core_ids = original
    where = path.name
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None: problems.append(where + ': corrupt member')
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)): problems.append(where + ': duplicate members')
        tops = {n.split('/')[0] for n in names}
        if len(tops) != 1: problems.append(where + ': expected one top folder, got %s' % sorted(tops)[:5]); return
        top = tops.pop()
        for i in infos:
            n = i.filename
            p = PurePosixPath(n)
            if p.is_absolute() or '..' in p.parts or '\\' in n or not n.isascii() or '__pycache__' in n:
                problems.append(where + ': bad member name ' + n)
            if (i.external_attr >> 16) & 0o170000 == 0o120000: problems.append(where + ': symlink ' + n)
        if top + '/SKILL.md' not in names: problems.append(where + ': no SKILL.md in top folder'); return
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            root = Path(tmp) / top
            skill_md = (root / 'SKILL.md').read_text(encoding='utf-8')
            meta = frontmatter(skill_md, where + ':SKILL.md', problems)
            if meta.get('name') != top: problems.append(where + ': name %r differs from folder %r' % (meta.get('name'), top))
            for ref in sorted(set(PATH_RE.findall(skill_md))):
                if '<' in ref or ref.endswith('/'):
                    if ref.endswith('/') and not (root / ref).is_dir() and '<' not in ref:
                        problems.append(where + ': missing folder ' + ref)
                    continue
                if not (root / ref).exists(): problems.append(where + ': SKILL.md points to missing ' + ref)
            # library: byte-identical, links resolve
            cat = json.loads((root / 'library/catalog.json').read_text(encoding='utf-8'))
            for w in cat['workflows']:
                placed.setdefault(w['id'], set()).add(top)
                ins = root / 'library/skills' / w['id'] / 'INSTRUCTIONS.md'
                if not ins.is_file(): problems.append(where + ': missing ' + w['id']); continue
                text = ins.read_text(encoding='utf-8')
                for link in re.findall(r'\]\(([^)#]+)\)', text) + re.findall(r'`(\.\./\.\./[^`]+)`', text):
                    if not (ins.parent / link).exists(): problems.append(where + ': %s link %s unresolved' % (w['id'], link))
                m = re.search(r'are relative to `(\.\./\.\./[^`]+)`', text)
                if m and not (ins.parent / m.group(1)).is_dir(): problems.append(where + ': %s resource dir missing' % w['id'])
            for p in (root / 'library').rglob('*'):
                rel = p.relative_to(root / 'library').as_posix()
                if p.is_file() and rel not in ('catalog.json', 'INDEX.md', 'skillset.json', 'sources.json', 'RUNTIME.md'):
                    if rel not in lib or sha(lib[rel]) != sha(p.read_bytes()):
                        problems.append(where + ': library file differs from original ' + rel)
            # core completeness
            core_here = sorted(d.name for d in (root / 'core').iterdir())
            for cid in core_here:
                placed.setdefault(cid, set()).add(top)
                for line in core_body_lines(files['core/%s/WORKFLOW.md' % cid].decode('utf-8')):
                    if line not in skill_md: problems.append(where + ': %s line lost in SKILL.md: %s' % (cid, line[:60]))
                for name in files:
                    if name.startswith('core/%s/' % cid) and not name.endswith('WORKFLOW.md'):
                        if sha((root / name).read_bytes()) != sha(files[name]): problems.append(where + ': core file changed ' + name)
            # the skill's own tools
            for cmd in ('check', 'selftest'):
                r = subprocess.run([sys.executable, str(root / 'scripts/sense.py'), cmd], capture_output=True, text=True, timeout=600, cwd=tmp)
                try:
                    status = json.loads(r.stdout)['status']
                except (ValueError, KeyError):
                    status = 'unreadable: ' + (r.stderr or r.stdout)[-300:]
                if status != 'ok': problems.append(where + ': sense.py %s -> %s' % (cmd, status))
            return {'file': path.name, 'name': top, 'bytes': path.stat().st_size, 'members': len(names),
                    'library': len(cat['workflows']), 'core': core_here, 'skill_md_bytes': len(skill_md.encode())}


def check_md(path, skill_names, original, problems):
    files = original[0]
    text = path.read_text(encoding='utf-8')
    meta = frontmatter(text, path.name, problems)
    if meta.get('name') not in skill_names: problems.append(path.name + ': name not among .skill names')
    core = sorted(set(re.findall(r'^### `([a-z0-9-]+)` — ', text, re.M)))
    for cid in core:
        for line in core_body_lines(files['core/%s/WORKFLOW.md' % cid].decode('utf-8')):
            if line not in text: problems.append(path.name + ': %s line lost: %s' % (cid, line[:60]))
    printed = set(re.findall(r'^### `(core/[^`]+)`', text, re.M))
    skill_only = set()
    m = re.search(r'In the \.skill edition only: (.*)', text)
    if m: skill_only = set(re.findall(r'`([^`]+)`', m.group(1)))
    for ref in set(PATH_RE.findall(text)):
        if ref.startswith('core/') and '<' not in ref and ref not in printed | skill_only:
            problems.append(path.name + ': mentions %s but neither prints it nor marks it .skill-only' % ref)
    return {'file': path.name, 'name': meta.get('name'), 'bytes': len(text.encode()), 'core': core}


def main(argv):
    if len(argv) != 2:
        print(__doc__); return 2
    original = load_original(argv[0])
    dist = Path(argv[1])
    problems, placed = [], {}
    skills = [check_skill(p, original, problems, placed) for p in sorted((dist / 'skill').glob('*.skill'))]
    names = {s['name'] for s in skills if s}
    mds = [check_md(p, names, original, problems) for p in sorted((dist / 'md').glob('*.md'))]
    _, _, catalog, core_ids = original
    expected = set(core_ids) | {w['id'] for w in catalog['workflows']}
    if set(placed) != expected:
        problems.append('placement differs: missing %s extra %s' % (sorted(expected - set(placed))[:5], sorted(set(placed) - expected)[:5]))
    core_count = {c: len(placed.get(c, ())) for c in core_ids}
    if any(v != 1 for v in core_count.values()): problems.append('each core workflow must be in exactly one skill')
    if len(skills) != len(mds): problems.append('different number of .skill and .md files')
    result = {'status': 'ok' if not problems else 'problems', 'problems': problems,
              'skills': skills, 'md': mds, 'core_workflows_placed': len(core_count),
              'library_workflows_placed': len(set(placed) - set(core_ids)),
              'library_workflows_in_more_than_one_skill': sum(1 for k, v in placed.items() if k not in core_count and len(v) > 1)}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
