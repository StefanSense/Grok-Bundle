#!/usr/bin/env python3
"""Stefan Sense Bundle for Grok - workflow router for ONE skill of the set.

Run from anywhere; paths are resolved against the skill folder (the folder with SKILL.md).

  python scripts/sense.py search "landing page copy"   # core + library of this skill, best first
  python scripts/sense.py show <id>                     # print a workflow (core or library)
  python scripts/sense.py where <id>                    # which skill of the set holds a workflow
  python scripts/sense.py list [--core | --library] [--category marketing]
  python scripts/sense.py check                         # integrity of this skill's files and syntax
  python scripts/sense.py doctor [workflow-id]          # real import/version probes, no installs
  python scripts/sense.py selftest                      # local smoke tests of this skill

Standard library only, no network access, never executes workflow helpers.
Author: M. Stefan Kassem (Stefan Sense). MIT licence.
"""
import argparse, hashlib, json, re, sys, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_probe import probe_module, probe_tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / 'core'
LIB = ROOT / 'library'
LIB_CATALOG = LIB / 'catalog.json'
SKILLSET = LIB / 'skillset.json'
MANIFEST = ROOT / 'manifest.json'
NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

# Russian (and a few colloquial) words -> English search terms.
ALIASES = {
    'напиши': 'write', 'статью': 'write article', 'статья': 'write article', 'пост': 'social post',
    'письмо': 'email', 'переписка': 'email', 'ответ': 'email reply', 'редактура': 'edit',
    'вычитка': 'edit proofread', 'отредактируй': 'edit', 'ошибки': 'edit proofread',
    'очеловечь': 'humanize', 'канцелярит': 'humanize-ru', 'нейросеть': 'humanize', 'штампы': 'humanize',
    'русский': 'humanize-ru russian', 'перевод': 'translate', 'переведи': 'translate', 'локализация': 'translate localize',
    'кратко': 'summarize', 'выжимка': 'summarize', 'конспект': 'summarize', 'суммируй': 'summarize',
    'реклама': 'ad-creative ads paid-ads', 'креатив': 'ad-creative creative', 'объявление': 'ad-creative',
    'копирайтинг': 'copywriting', 'лендинг': 'copywriting landing page-cro', 'оффер': 'copywriting offer',
    'соцсети': 'social', 'телеграм': 'social telegram', 'линкедин': 'linkedin social',
    'контент': 'content-plan content', 'контент-план': 'content-plan', 'сео': 'seo', 'семантика': 'seo keywords',
    'позиционирование': 'product-marketing positioning', 'бренд': 'brand product-marketing brand-voice',
    'исследование': 'research', 'исследуй': 'research', 'источники': 'research sources', 'рынок': 'strategy market research',
    'конкуренты': 'strategy competitor competitive', 'факты': 'fact-check', 'фактчекинг': 'fact-check', 'проверь': 'fact-check review',
    'данные': 'data-analysis data', 'анализ': 'data-analysis analysis', 'статистика': 'data-analysis statistical',
    'график': 'data-analysis chart', 'решение': 'decision', 'выбор': 'decision', 'риски': 'decision risk',
    'стратегия': 'strategy', 'бизнес-план': 'strategy business', 'юнит-экономика': 'strategy unit economics finance',
    'встреча': 'meeting', 'протокол': 'meeting minutes', 'повестка': 'meeting agenda', 'созвон': 'meeting',
    'проект': 'project-plan project', 'сроки': 'project-plan', 'продукт': 'product', 'тз': 'product prd',
    'продажи': 'sales', 'кп': 'sales proposal', 'возражения': 'sales objection', 'резюме': 'career cv resume',
    'собеседование': 'career interview', 'обучение': 'learn', 'объясни': 'learn explain', 'промпт': 'prompt',
    'код': 'code', 'скрипт': 'code script', 'отладка': 'code debug', 'ревью': 'code review', 'sql': 'code sql',
    'документ': 'documents docx', 'ворд': 'documents docx', 'word': 'documents docx', 'пдф': 'documents pdf',
    'pdf': 'documents pdf', 'эксель': 'spreadsheets xlsx', 'excel': 'spreadsheets xlsx', 'таблица': 'spreadsheets xlsx',
    'презентация': 'presentations pptx slides', 'слайды': 'presentations slides', 'powerpoint': 'presentations pptx',
    'картинка': 'visual image', 'изображение': 'visual image', 'схема': 'visual diagram', 'диаграмма': 'visual diagram',
    'договор': 'contract-review contract', 'контракт': 'contract-review', 'юрист': 'contract-review legal',
    'планирование': 'productivity plan', 'задачи': 'productivity tasks', 'цели': 'productivity goals okr',
    'питч': 'pitch deck investor presentations', 'инвесторов': 'investor', 'инвестор': 'investor',
    'тест': 'testing test', 'автотесты': 'testing e2e playwright', 'безопасность': 'security', 'аудит': 'audit', 'соответствие': 'compliance', 'персональные': 'gdpr privacy', 'тесты': 'testing test', 'финансы': 'finance financial', 'комплаенс': 'compliance',
}
STOP = set('the a an and or of for to in on with my me i you it this that как и в на с для по мне мой это что'.split())


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    data = {}
    if m:
        for line in m.group(1).splitlines():
            if ':' in line and not line.startswith((' ', '\t')):
                k, v = line.split(':', 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] == '"':
                    try: v = json.loads(v)
                    except ValueError: v = v[1:-1]
                data[k.strip()] = v
    return data


def skillset():
    return _json(SKILLSET)


def this_skill():
    return skillset()['this_skill']


def core_index():
    items = []
    for wf in sorted(CORE.glob('*/WORKFLOW.md')):
        meta = frontmatter(wf.read_text(encoding='utf-8'))
        items.append({'id': meta.get('id', wf.parent.name), 'title': meta.get('title', ''), 'tier': 'core',
                      'category': 'core', 'description': meta.get('description', ''),
                      'path': wf.relative_to(ROOT).as_posix()})
    return items


def library_items():
    if not LIB_CATALOG.exists():
        return []
    return [dict(w, tier='library') for w in _json(LIB_CATALOG).get('workflows', [])]


def all_items():
    return core_index() + library_items()


def normalize_id(ident):
    ident = ident.strip().lower().lstrip('@$/')
    return ident[5:] if ident.startswith('work-') else ident


def find(ident):
    ident = normalize_id(ident)
    for item in all_items():
        if item['id'] == ident:
            return item
    return None


def where(ident):
    ident = normalize_id(ident)
    data = skillset()
    entry = data['workflows'].get(ident)
    if not entry:
        return {'id': ident, 'found': False, 'note': 'Not part of any skill of this set.'}
    titles = {s['slug']: s['title'] for s in data['skills']}
    here = data['this_skill']['slug'] in entry['skills']
    return {'id': ident, 'found': True, 'tier': entry['tier'], 'title': entry['title'], 'in_this_skill': here,
            'skills': [{'slug': s, 'title': titles.get(s, s)} for s in entry['skills']]}


def tokens(text):
    return [t for t in re.findall(r'[\w][\w+#.-]*', text.lower()) if t not in STOP]


def _weights(q):
    words = [w for w in tokens(q) if not w.isdigit()]
    raw = tokens(q)
    weights = {w: 1.0 for w in words}
    for a, b in zip(raw, raw[1:]):  # "soc 2" -> soc2 / soc-2, "page cro" -> page-cro
        weights.setdefault(a + b, 1.0); weights.setdefault(a + '-' + b, 1.0)
    for w in words:  # Russian words -> English terms; aliases count less than literal words
        hits = ALIASES.get(w, '').split()
        if not hits and len(w) > 5:  # crude stemming: share the first 5 letters with an alias key
            hits = [t for k, v in ALIASES.items() if k[:5] == w[:5] for t in v.split()]
        for t in hits:
            weights.setdefault(t, 0.7)
    return weights


def _score(item, weights, cyrillic):
    ident = item['id']
    id_parts = set(ident.split('-'))
    title_words = set(tokens(item.get('title', '')))
    desc_words = set(tokens(item.get('description', '')))
    score = 0
    for t, wt in weights.items():
        s = 0
        if t == ident: s += 50
        elif t in id_parts: s += 12
        elif len(t) >= 4 and t in ident: s += 6
        if t in title_words: s += 5
        elif len(t) >= 4 and any(w.startswith(t) for w in title_words): s += 3
        if t in desc_words: s += 2
        elif len(t) >= 5 and any(w.startswith(t) for w in desc_words): s += 1
        score += s * wt
    if score >= 10 and ident.endswith(('-ru', '-en')):  # language-specific workflows follow the query language
        score += 8 if ident.endswith('-ru') == cyrillic else -8
    score = int(round(score))
    if score > 0 and item['tier'] == 'core':
        score = int(score * 1.3) + 2
    return score


def search(query, limit=8, tier=None):
    q = normalize_id(query)
    weights = _weights(q)
    cyrillic = bool(re.search('[а-яё]', q))
    exact = find(q)
    scored = []
    for item in all_items():
        if tier and item['tier'] != tier:
            continue
        s = _score(item, weights, cyrillic)
        if s > 0:
            scored.append((s, item))
    scored.sort(key=lambda p: (-p[0], p[1]['tier'] != 'core', p[1]['id']))
    out = [dict(_short(i), score=s) for s, i in scored[:limit]]
    if exact and (tier is None or exact['tier'] == tier) and (not out or out[0]['id'] != exact['id']):
        out = [o for o in out if o['id'] != exact['id']]
        out.insert(0, dict(_short(exact), score='exact'))
    # Workflows of the other skills (titles only) - so a request outside this skill is routed, not improvised.
    local = {i['id'] for i in all_items()}
    data = skillset()
    titles = {s['slug']: s['title'] for s in data['skills']}
    others = []
    for ident, entry in data['workflows'].items():
        if ident in local:
            continue
        s = _score({'id': ident, 'title': entry['title'], 'tier': entry['tier']}, weights, cyrillic)
        if s >= 12:
            others.append((s, ident, entry))
    others.sort(key=lambda p: (-p[0], p[1]))
    elsewhere = [{'id': i, 'title': e['title'], 'skills': [titles.get(s, s) for s in e['skills']]} for _, i, e in others[:3]]
    return {'results': out[:limit], 'elsewhere': elsewhere}


def _short(item):
    keep = ('id', 'tier', 'category', 'title', 'description')
    d = {k: item.get(k, '') for k in keep}
    if len(d['description']) > 240:
        d['description'] = d['description'][:237] + '...'
    return d


def library_paths(item):
    base = LIB / 'skills' / item['id']
    return {'instructions': base / 'INSTRUCTIONS.md', 'workflow': base / 'references' / 'workflow.md',
            'runtime': LIB / 'RUNTIME.md'}


def show(ident):
    item = find(ident)
    if not item:
        w = where(ident)
        if w.get('found'):
            raise ValueError('"%s" is not in this skill; it is in: %s' % (w['id'], ', '.join(s['title'] for s in w['skills'])))
        raise ValueError('unknown workflow "%s" - try: sense.py search "%s"' % (ident, ident))
    if item['tier'] == 'core':
        return (ROOT / item['path']).read_text(encoding='utf-8')
    p = library_paths(item)
    parts = [p['runtime'].read_text(encoding='utf-8'), p['instructions'].read_text(encoding='utf-8')]
    if p['workflow'].exists():
        parts.append(p['workflow'].read_text(encoding='utf-8'))
    parts.append('\n[workflow folder: %s; shared rules: %s; helpers were NOT executed]' % (
        p['instructions'].parent.relative_to(ROOT).as_posix(), p['runtime'].relative_to(ROOT).as_posix()))
    return '\n\n'.join(parts)


def _check_skill_md(problems):
    text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        problems.append('SKILL.md: frontmatter missing'); return
    meta = frontmatter(text)
    name, desc = meta.get('name', ''), meta.get('description', '')
    if not NAME_RE.match(name) or len(name) > 64: problems.append('SKILL.md: invalid name')
    if not desc or len(desc) > 1024 or '<' in desc or '>' in desc: problems.append('SKILL.md: invalid description')
    if name != this_skill()['slug']: problems.append('SKILL.md: name differs from skillset.json')


def check():
    """Check packaged files, checksums and syntax. Does not certify external services or run helpers."""
    problems = []
    manifest = _json(MANIFEST)
    if manifest.get('schema') != 2 or not isinstance(manifest.get('files'), dict):
        return {'status': 'problems', 'problem_count': 1, 'problems': ['invalid manifest.json']}
    files = manifest['files']
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.name != 'manifest.json'}
    for name in sorted(set(files) - actual): problems.append('missing file: ' + name)
    for name in sorted(actual - set(files)): problems.append('unexpected file: ' + name)
    python_count = 0
    for name, digest in files.items():
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            problems.append('checksum mismatch: ' + name); continue
        try:
            if name.endswith('.py'):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', SyntaxWarning)
                    compile(data, name, 'exec')
                python_count += 1
            elif name.endswith('.json'):
                json.loads(data)
        except (ValueError, SyntaxError, UnicodeError) as e:
            problems.append(name + ': ' + str(e))
    core = core_index()
    lib = library_items()
    ids = [i['id'] for i in core + lib]
    if len(ids) != len(set(ids)): problems.append('duplicate workflow ids')
    expected = this_skill()
    if sorted(c['id'] for c in core) != sorted(expected['core']): problems.append('core workflow set differs from skillset.json')
    if len(lib) != expected['library_count']: problems.append('library count differs from skillset.json')
    for c in core:
        if not c['description']: problems.append('missing description: ' + c['id'])
    for w in lib:
        req = manifest.get('workflows', {}).get(w['id'], {}).get('required_files')
        if not req: problems.append('missing workflow manifest: ' + w['id']); continue
        for name in req:
            if name not in files: problems.append(w['id'] + ': missing dependency ' + name)
    try:
        _check_skill_md(problems)
    except (OSError, KeyError) as e:
        problems.append('SKILL.md: ' + str(e))
    return {'skill': expected['slug'], 'core_workflows': len(core), 'library_workflows': len(lib),
            'files': len(files), 'python_files_compiled': python_count,
            'status': 'ok' if not problems else 'problems', 'problem_count': len(problems), 'problems': problems[:100],
            'scope': 'Integrity, required resources and Python/JSON syntax only; run selftest for local functions and doctor for runtime dependencies. External services are not certified.'}


def doctor(workflow=None):
    modules = ['docx', 'openpyxl', 'pptx', 'reportlab', 'pypdf', 'pandas', 'matplotlib']
    local = []
    if workflow:
        item = find(workflow)
        if not item: raise ValueError('workflow is not in this skill: ' + workflow)
        if item['tier'] == 'library':
            meta = _json(MANIFEST)['workflows'][item['id']]
            modules = meta.get('external_imports', [])
            local = meta.get('local_imports', [])
    return {'python': sys.version.split()[0], 'modules': {m: probe_module(m) for m in modules},
            'tools': {t: probe_tool(t) for t in ('soffice', 'pdftoppm', 'tesseract')},
            'workflow': workflow, 'bundled_imports': local, 'skill_root': str(ROOT),
            'note': 'Import/version probes only. API access, credentials and workflow outputs need a task-specific check; missing optional dependencies are reported, never installed automatically.'}


def list_items(category=None, tier=None):
    out = []
    for i in all_items():
        if tier and i['tier'] != tier: continue
        if category and i.get('category') != category: continue
        out.append({'id': i['id'], 'tier': i['tier'], 'category': i.get('category'), 'title': i.get('title')})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Stefan Sense Bundle for Grok - skill router')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('search'); p.add_argument('query', nargs='+'); p.add_argument('--limit', type=int, default=8)
    p.add_argument('--core', action='store_true', help='core workflows only')
    p = sub.add_parser('show'); p.add_argument('id')
    p = sub.add_parser('where'); p.add_argument('id')
    p = sub.add_parser('list'); p.add_argument('--category'); p.add_argument('--core', action='store_true')
    p.add_argument('--library', action='store_true')
    sub.add_parser('check'); p = sub.add_parser('doctor'); p.add_argument('workflow', nargs='?')
    sub.add_parser('selftest')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'search':
            res = search(' '.join(a.query), max(1, min(a.limit, 30)), 'core' if a.core else None)
        elif a.cmd == 'show':
            print(show(a.id)); return 0
        elif a.cmd == 'where':
            res = where(a.id)
        elif a.cmd == 'list':
            res = list_items(a.category, 'core' if a.core else 'library' if a.library else None)
        elif a.cmd == 'check':
            res = check()
        elif a.cmd == 'selftest':
            from selftest import run
            res = run()
        else:
            res = doctor(a.workflow)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1 if a.cmd in ('check', 'selftest') and res['status'] not in ('ok', 'partial') else 0
    except (ValueError, OSError, KeyError, TypeError) as e:
        print('error: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
