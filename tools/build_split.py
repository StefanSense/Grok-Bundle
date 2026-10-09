#!/usr/bin/env python3
"""Build the split Grok edition of Stefan Sense Bundle.

Turns the full bundle ZIP (one big skill with a packed library) into standalone skills, one per
area of work. Every skill is produced in two formats:

  dist/skill/NN_<Title>.skill   ZIP with <slug>/SKILL.md, core workflows, the area's specialist
                                library (unpacked), helper scripts, licences and a checksum manifest
  dist/md/NN_<Title>.md         single Markdown file: rules, complete core workflows, short
                                reference sheets, library index and licence texts

  python tools/build_split.py Stefan_Sense_Bundle_Grok.zip [--out dist] [--work build]

Source checksums (catalog, manifest, library.zip) are verified before anything is written.
Standard library only. Author of the bundle: M. Stefan Kassem (Stefan Sense), MIT licence.
"""
import argparse, hashlib, io, json, re, shutil, sys, zipfile
from pathlib import Path, PurePosixPath

VERSION = '1.2.0-grok-split'
HERE = Path(__file__).resolve().parent
ZIP_DATE = (2026, 10, 9, 0, 0, 0)
MD_SHORT_REFERENCE_LIMIT = 10_000  # bytes; longer reference files stay in the .skill edition only

CATEGORY_HOME = {
    'marketing': 'marketing-sales', 'research': 'analysis', 'finance': 'analysis',
    'business': 'work-management', 'leadership': 'work-management', 'project-management': 'work-management',
    'operations': 'work-management', 'product': 'work-management', 'compliance': 'work-management',
    'productivity': 'personal-growth', 'documents': 'documents-visuals', 'design': 'documents-visuals',
    'media': 'documents-visuals', 'engineering': 'code-ai',
}
# Library workflows whose upstream category does not match the area where people look for them.
OVERRIDES = {
    'texts-languages': ['article-writing', 'content-humanizer', 'behuman'],
    'marketing-sales': ['channel-economics', 'commercial-forecaster', 'commercial-policy', 'commercial-skills',
                        'customer-success-manager', 'deal-desk', 'partnerships-architect', 'pricing-strategist',
                        'revenue-operations', 'rfp-responder', 'sales-engineer'],
    'analysis': ['andreessen', 'roast', 'statistical-analyst', 'senior-data-scientist', 'data-quality-auditor',
                 'benchmark-methodology', 'competitive-platform-analysis', 'competitive-report-structure'],
    'work-management': ['meetings', 'interview-system-designer'],
    'documents-visuals': ['google-workspace-ops', 'demo-video', 'ecc-design-system'],
    'code-ai': ['prompt-engineer-toolkit', 'skill-creator'],
}

SKILLS = [
    {
        'key': 'texts-languages', 'title': 'Тексты и языки', 'title_en': 'Texts and languages',
        'core': ['write', 'edit', 'humanize-ru', 'humanize-en', 'translate', 'summarize', 'email'],
        'scripts': ['text_scan.py'],
        'scope': 'writing, editing, humanizing, translation, summaries, business email',
        'table': [
            ('Write any text: post, article, letter, announcement, instructions, speech', '`write`'),
            ('Edit, proofread or polish an existing text', '`edit`'),
            ('Remove AI tells and bureaucratese — Russian / English', '`humanize-ru` · `humanize-en`'),
            ('Translate, localize, bilingual review', '`translate`'),
            ('Summarize documents, articles, chats, transcripts', '`summarize`'),
            ('Business email, messenger messages, follow-ups, replies', '`email`'),
        ],
        'smoke': [('очеловечь', 'humanize-ru'), ('переведи', 'translate'), ('выжимка', 'summarize'), ('вычитка', 'edit')],
        'description': (
            'Тексты и языки (Stefan Sense). Write, edit and proofread texts in Russian or English; remove AI tells '
            'and bureaucratese; translate and localize; summarize documents, chats and transcripts; write business '
            'emails and messenger replies. {n_core} core workflows plus {n_lib} specialist workflows (article writing, '
            'brand voice, content humanizer, cold email, email sequences, localization). Use for: напиши текст, статья, отредактируй, вычитай, '
            'очеловечь, убери канцелярит, переведи, перевод, локализация, кратко, выжимка, конспект, письмо, ответ '
            'клиенту, write, edit, proofread, humanize, translate, summarize, email.'),
    },
    {
        'key': 'marketing-sales', 'title': 'Маркетинг и продажи', 'title_en': 'Marketing and sales',
        'core': ['copywriting', 'ad-creative', 'social', 'product-marketing', 'content-plan', 'seo', 'sales'],
        'scripts': [],
        'scope': 'copy, ads, social media, positioning, content plans, SEO, sales and pricing',
        'table': [
            ('Selling copy: landing pages, offers, headlines, CTAs, product descriptions', '`copywriting`'),
            ('Ads and creatives for Google, Meta, Yandex Direct, VK, TikTok, X', '`ad-creative`'),
            ('Social posts, X threads, Telegram, short video scripts', '`social`'),
            ('Positioning, audience, brand/product context document', '`product-marketing`'),
            ('Content strategy and editorial calendar', '`content-plan`'),
            ('SEO (Google, Yandex) and AI-answer visibility', '`seo`'),
            ('Sales: proposals (КП), discovery, objections, outreach, RFP', '`sales`'),
        ],
        'smoke': [('лендинг', 'copywriting'), ('реклама', 'ad-creative'), ('контент-план', 'content-plan'), ('возражения', 'sales')],
        'description': (
            'Маркетинг и продажи (Stefan Sense). Selling copy and landing pages, ads and creatives, social media and '
            'X posts, positioning and brand context, content plans, SEO and AI-search visibility, CRO, email '
            'sequences, sales proposals (КП), objections, cold outreach, pricing and RFP answers. {n_core} core '
            'workflows plus {n_lib} specialist marketing and sales workflows. Use for: реклама, креатив, лендинг, '
            'оффер, копирайтинг, пост, соцсети, телеграм, контент-план, SEO, семантика, позиционирование, бренд, КП, '
            'коммерческое предложение, продажи, возражения, холодное письмо, ценообразование, copywriting, ads, '
            'social media, SEO, sales.'),
    },
    {
        'key': 'analysis', 'title': 'Анализ', 'title_en': 'Analysis',
        'core': ['research', 'fact-check', 'data-analysis', 'decision', 'strategy'],
        'scripts': [],
        'scope': 'research with sources, fact-checking, data analysis, decisions, strategy, finance',
        'table': [
            ('Research a question with current, cited sources', '`research`'),
            ('Verify claims in a text, post, AI answer or report', '`fact-check`'),
            ('Analyze CSV/Excel data: statistics, trends, A/B tests, charts', '`data-analysis`'),
            ('Make or stress-test a decision; risks, pre-mortem', '`decision`'),
            ('Strategy, market sizing, competitors, business model', '`strategy`'),
        ],
        'smoke': [('фактчекинг', 'fact-check'), ('исследуй', 'research'), ('статистика', 'data-analysis'), ('стратегия', 'strategy')],
        'description': (
            'Анализ (Stefan Sense). Research with current cited sources, fact-checking of claims and AI answers, '
            'analysis of CSV and Excel data with statistics and charts, A/B tests, decisions and stress tests, '
            'strategy, market sizing, competitor analysis, finance (DCF, SaaS metrics, investment ROI). {n_core} core '
            'workflows plus {n_lib} specialist research, finance and statistics workflows. Use for: исследуй, найди '
            'источники, проверь факты, фактчекинг, проанализируй данные, статистика, график, помоги решить, риски, '
            'стратегия, рынок, конкуренты, финансы, research, fact-check, data analysis, decision, strategy.'),
    },
    {
        'key': 'work-management', 'title': 'Работа и менеджмент', 'title_en': 'Work and management',
        'core': ['meeting', 'project-plan', 'product', 'contract-review'],
        'scripts': [],
        'scope': 'meetings, projects, product management, contracts, leadership, operations, compliance',
        'table': [
            ('Meetings: is it needed, agenda, minutes, decisions, action items', '`meeting`'),
            ('Project plans: scope, timeline, RACI, risks, status reports', '`project-plan`'),
            ('Product: discovery, PRD, user stories, prioritization, roadmap', '`product`'),
            ('Contract, offer, NDA or terms review', '`contract-review`'),
            ('Leadership and C-level advice, operations, Jira/Confluence, compliance (GDPR, ISO, SOC 2, EU AI Act)', 'library — see below'),
        ],
        'smoke': [('протокол', 'meeting'), ('договор', 'contract-review'), ('тз', 'product'), ('SOC 2', 'soc2-compliance')],
        'description': (
            'Работа и менеджмент (Stefan Sense). Meetings (agenda, minutes, action items), project plans, risks and '
            'status reports, product management (PRD, user stories, roadmap), contract review, leadership and C-level '
            'advisory, team and operations processes, Jira, Confluence and Scrum, compliance (GDPR, ISO 27001, SOC 2, '
            'EU AI Act, ISO 13485). {n_core} core workflows plus {n_lib} specialist workflows. Use for: встреча, '
            'протокол, повестка, проект, план проекта, сроки, риски, продукт, ТЗ, PRD, договор, проверь договор, '
            'руководитель, команда, процессы, комплаенс, meeting, project plan, product, contract, management, '
            'leadership, compliance.'),
    },
    {
        'key': 'personal-growth', 'title': 'Личное развитие', 'title_en': 'Personal growth',
        'core': ['career', 'learn', 'productivity'],
        'scripts': [],
        'scope': 'career and CV, learning, personal productivity and planning',
        'table': [
            ('CV/resume for a vacancy, cover letter, LinkedIn/HH profile, interview prep', '`career`'),
            ('Learn anything: explanations, tutoring, study plans, flashcards, quizzes', '`learn`'),
            ('Brain dump to tasks, priorities, day/week plans, goals, weekly review', '`productivity`'),
        ],
        'smoke': [('резюме', 'career'), ('собеседование', 'career'), ('объясни', 'learn'), ('планирование', 'productivity')],
        'description': (
            'Личное развитие (Stefan Sense). Career: CV and resume for a vacancy, cover letter, LinkedIn or HH '
            'profile, interview preparation. Learning: explanations at the right level, tutoring, study plans, '
            'flashcards, quizzes, language learning. Personal productivity: brain dump to tasks, priorities, day and '
            'week planning, deep work, weekly review, inbox triage, reflection. {n_core} core workflows plus {n_lib} '
            'specialist workflows. Use for: резюме, сопроводительное письмо, собеседование, карьера, объясни, научи, '
            'план обучения, учить язык, планирование, задачи, приоритеты, цели, продуктивность, CV, interview, '
            'learn, productivity.'),
    },
    {
        'key': 'documents-visuals', 'title': 'Документы и визуал', 'title_en': 'Documents and visuals',
        'core': ['documents', 'spreadsheets', 'presentations', 'visual'],
        'scripts': ['docs.py'],
        'scope': 'Word, PDF, Excel, PowerPoint files, slides, images, diagrams, design, video',
        'table': [
            ('Word (.docx) and PDF: create, read, edit, convert, check', '`documents`'),
            ('Excel/CSV/Google Sheets: trackers, budgets, models, formulas', '`spreadsheets`'),
            ('Presentations: storyline, slides, speaker notes, .pptx', '`presentations`'),
            ('Visuals: image prompts, diagrams, infographics, posters, design', '`visual`'),
        ],
        'smoke': [('презентация', 'presentations'), ('эксель', 'spreadsheets'), ('ворд', 'documents'), ('диаграмма', 'visual')],
        'description': (
            'Документы и визуал (Stefan Sense). Create, read, edit and check Word (.docx), PDF, Excel/CSV and '
            'PowerPoint (.pptx) files; spreadsheets with formulas, budgets and trackers; presentation storylines and '
            'slides; visuals: image prompts, diagrams, infographics, posters, themes and design systems, HTML slides '
            'and documents, video and media. Includes a local document helper (docs.py). {n_core} core workflows '
            'plus {n_lib} specialist workflows. Use for: документ, Word, ворд, PDF, пдф, Excel, эксель, таблица, '
            'презентация, слайды, PowerPoint, картинка, изображение, схема, диаграмма, инфографика, дизайн, видео, '
            'docx, xlsx, pptx, visual.'),
    },
    {
        'key': 'code-ai', 'title': 'Код и ИИ', 'title_en': 'Code and AI',
        'core': ['code', 'prompt'],
        'scripts': [],
        'scope': 'programming, engineering frameworks, DevOps, security, prompts, skills and AI agents',
        'table': [
            ('Write, review, debug, refactor and test code; SQL; scripts', '`code`'),
            ('Prompts, system and custom instructions, AGENTS.md, SKILL.md skills', '`prompt`'),
            ('Frameworks, languages, cloud, DevOps, security, testing, AI agents, RAG', 'library — see below'),
        ],
        'smoke': [('отладка', 'code'), ('промпт', 'prompt'), ('playwright', 'playwright-pro')],
        'description': (
            'Код и ИИ (Stefan Sense). Programming help: write, review, debug, refactor and test code; SQL; '
            'architecture, APIs, frameworks and languages, DevOps, cloud, security and testing; prompts, system and '
            'custom instructions, AGENTS.md and SKILL.md skills; AI agents, RAG and LLM engineering. {n_core} core '
            'workflows plus {n_lib} specialist engineering workflows. Use for: код, скрипт, отладка, ошибка, ревью '
            'кода, SQL, тесты, архитектура, промпт, системный промпт, навык, агент, code, debug, refactor, code '
            'review, prompt, skill, agent, API, Python, JavaScript.'),
    },
]
for _i, _s in enumerate(SKILLS, 1):
    _s['n'] = _i
    _s['slug'] = 'stefan-sense-' + _s['key']
    _s['stem'] = '%02d_%s' % (_i, _s['title'].replace(' ', '_'))

RULES = """## Operating rules (always on)
1. **Accuracy first.** Never invent facts, numbers, quotes, sources, links, test results or file contents. Unknown → say "I don't know / not enough reliable data", or mark `[NEED: …]` / `[ASSUMPTION]`. Separate facts, estimates and opinions.
2. **Sources.** Current facts (prices, laws, specs, news, people) need live sources when web search is available; otherwise state that the answer comes from model knowledge and may be outdated. Posts found through X search are statements of their authors, not verification: use them for "what people say now", confirm facts with primary sources, and label claims that rest only on X posts.
3. **Language.** Reply in the user's language; keep the user's terms, names and voice.
4. **Ask little, deliver.** Ask at most 3 questions, and only when the answer changes the result; otherwise proceed and list assumptions.
5. **Real tools only.** Use only capabilities present in this session (web and X search, code execution, files, image generation, connectors, Tasks/Automations, shell and file tools in Grok Build). Never claim an action, file, email, post or saved memory that did not happen. Sending, publishing, purchasing or deleting needs explicit user authorization; an already explicit request is authorization for its stated scope. Respect host approval controls.
6. **Independent judgment.** Do not agree by default; if an idea or text is weak, say why and offer a stronger version.
7. **Tone.** The selected Grok personality or mode never overrides rules 1–6. Deliverables (texts, documents, reports) use the register the task needs, not chat banter, unless the user asks for it.
8. **Self-check before answering:** unsupported claims? broken logic? numbers recomputed? deliverable matches the request?
"""

PROJECT_LICENSE = {  # origin project -> licence file in library/licenses
    'claude-skills': 'LICENSE-claude-skills.txt',
    'everything-claude-code (ECC)': 'LICENSE-everything-claude-code.txt',
    'anthropics/skills (example skills)': 'LICENSE-Apache-2.0.txt',
    'marketingskills': 'LICENSE-marketingskills.txt',
    'humanizer': 'LICENSE-humanizer.txt',
    'Loop Library (via claude-skills)': 'LICENSE-loop-library.txt',
}


# How the based_on line of a core workflow names each project.
BASIS_NEEDLES = {
    'claude-skills': ['claude-skills'],
    'everything-claude-code (ECC)': ['ECC', 'everything-claude-code'],
    'anthropics/skills (example skills)': ['Anthropic'],
    'marketingskills': ['marketingskills'],
    'humanizer': ['humanizer'],
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fail(msg):
    raise SystemExit('build error: ' + msg)


def safe_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        fail('unsafe archive member: ' + name)
    return name


# ----------------------------------------------------------------------------- source

class Bundle:
    def __init__(self, zip_path):
        with zipfile.ZipFile(zip_path) as z:
            roots = [n[:-len('SKILL.md')] for n in z.namelist() if n.endswith('/SKILL.md') and n.count('/') == 1]
            if len(roots) != 1:
                fail('expected exactly one <folder>/SKILL.md at the top of the bundle ZIP')
            prefix = roots[0]
            self.files = {}
            for info in z.infolist():
                if info.is_dir() or not info.filename.startswith(prefix):
                    continue
                self.files[safe_name(info.filename[len(prefix):])] = z.read(info)
        self.manifest = json.loads(self.files['library/manifest.json'])
        self.catalog = json.loads(self.files['library/catalog.json'])
        self.sources = json.loads(self.files['library/sources.json'])
        for name, digest in self.manifest['bundle_files'].items():
            if name not in self.files or sha256(self.files[name]) != digest:
                fail('bundle file checksum mismatch: ' + name)
        lib_zip = self.files['library/library.zip']
        if sha256(lib_zip) != self.catalog['library_sha256']:
            fail('library.zip checksum mismatch')
        self.lib = {}
        with zipfile.ZipFile(io.BytesIO(lib_zip)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                data = z.read(info)
                name = safe_name(info.filename)
                if sha256(data) != self.manifest['files'].get(name):
                    fail('library file checksum mismatch: ' + name)
                self.lib[name] = data
        if set(self.lib) != set(self.manifest['files']):
            fail('library inventory differs from manifest')
        self.workflows = {w['id']: w for w in self.catalog['workflows']}
        self.core_ids = sorted({n.split('/')[1] for n in self.files if n.startswith('core/') and n.endswith('/WORKFLOW.md')})
        self.version = self.files['VERSION'].decode().strip()

    def text(self, name):
        return self.files[name].decode('utf-8')

    def core_files(self, cid):
        return sorted(n for n in self.files if n.startswith('core/%s/' % cid))

    def workflow_files(self, wid):
        w = self.workflows[wid]
        out = set()
        for prefix in w['files']:
            p = prefix.rstrip('/') + '/'
            out.update(n for n in self.lib if n.startswith(p))
        # Some workflows also need shared files outside their own folders (agent personas, sibling
        # references); the manifest lists every required file, so those travel with the workflow.
        req = {r for r in self.manifest['workflows'][wid]['required_files']
               if not r.startswith('licenses/') and r != 'RUNTIME.md'}
        if req - set(self.lib):
            fail('%s: required files missing from the library: %s' % (wid, sorted(req - set(self.lib))[:3]))
        return sorted(out | req)


# ----------------------------------------------------------------------------- planning

def plan(bundle):
    by_key = {s['key']: s for s in SKILLS}
    core_seen = [c for s in SKILLS for c in s['core']]
    if sorted(core_seen) != bundle.core_ids or len(core_seen) != len(set(core_seen)):
        fail('core workflow mapping must cover each of the %d core workflows exactly once' % len(bundle.core_ids))
    home = {}
    for wid, w in bundle.workflows.items():
        home[wid] = CATEGORY_HOME[w['category']]
    for key, ids in OVERRIDES.items():
        for wid in ids:
            if wid not in bundle.workflows:
                fail('override names unknown workflow ' + wid)
            home[wid] = key
    for s in SKILLS:
        s['library'] = sorted(w for w, k in home.items() if k == s['key'])
        s['primary_count'] = len(s['library'])
    # A library workflow named by a core workflow travels with that core workflow (one copy per skill),
    # so every reference inside a skill resolves inside the same skill.
    pattern = re.compile(r'`([a-z0-9][a-z0-9-]+)`')
    core_home = {c: s['key'] for s in SKILLS for c in s['core']}
    for s in SKILLS:
        refs, foreign_core = set(), set()
        for cid in s['core']:
            text = bundle.text('core/%s/WORKFLOW.md' % cid)
            for ident in pattern.findall(text):
                if ident in bundle.workflows:
                    refs.add(ident)
                elif ident in core_home and core_home[ident] != s['key']:
                    foreign_core.add(ident)
            # The library workflows a core workflow is based on (its based_on line) travel with it too.
            basis = split_frontmatter(text)[0].get('based_on', '')
            refs.update(w for w in re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', basis) if w in bundle.workflows)
        s['shared'] = sorted(refs - set(s['library']))
        s['library'] = sorted(set(s['library']) | refs)
        s['foreign_core'] = sorted(foreign_core)
    placement = {}
    for s in SKILLS:
        for c in s['core']:
            placement.setdefault(c, {'tier': 'core', 'skills': []})['skills'].append(s['slug'])
        for w in s['library']:
            placement.setdefault(w, {'tier': 'library', 'skills': []})['skills'].append(s['slug'])
    missing = (set(bundle.workflows) | set(bundle.core_ids)) - set(placement)
    if missing:
        fail('workflows without a skill: %s' % sorted(missing))
    for s in SKILLS:
        other = next(o for o in SKILLS if o is not s)
        probe = next(w for w in other['library'] if s['slug'] not in placement[w]['skills'])
        s['where'] = [(probe, other['slug'])]
    return placement, by_key


# ----------------------------------------------------------------------------- text helpers

def split_frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    meta = {}
    if not m:
        return meta, text
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def demote(body, levels=2):
    """Lower Markdown heading levels outside fenced code blocks."""
    out, fence = [], None
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(('```', '~~~')):
            mark = stripped[:3]
            fence = None if fence == mark else (fence or mark)
        elif fence is None and re.match(r'#{1,6} ', line):
            hashes = len(line) - len(line.lstrip('#'))
            line = '#' * min(6, hashes + levels) + line[hashes:]
        out.append(line)
    return '\n'.join(out)


def rewrite_core_paths(body, cid):
    # Only concrete file paths (references/<file>); a bare `references/` describes the skill format in general.
    body = re.sub(r'(?<![\w/.])references/(?=[\w.-])', 'core/%s/references/' % cid, body)
    return re.sub(r'(?<![\w/.])assets/(?=[\w.-])', 'core/%s/assets/' % cid, body)


def replace_once(text, old, new, where):
    if text.count(old) != 1:
        fail('expected exactly one "%s" in %s' % (old, where))
    return text.replace(old, new)


def adapt_core(cid, text):
    if cid == 'documents':
        text = replace_once(text, '(paths relative to the bundle root)',
                            '(paths relative to the skill folder — the folder that contains SKILL.md)', cid)
    if cid == 'humanize-ru':
        text = replace_once(text, 'из корня бандла', 'из папки навыка (где лежит SKILL.md)', cid)
    return text


def adapt_runtime(text):
    text = replace_once(text, "or the bundle's SKILL.md.", "or the skill's SKILL.md.", 'RUNTIME.md')
    text = replace_once(text, 'run `sense.py doctor <workflow-id>` from the bundle and inspect its source.',
                        'run `python scripts/sense.py doctor <workflow-id>` from the skill folder (the folder with '
                        'SKILL.md) and inspect its source.', 'RUNTIME.md')
    return replace_once(text, 'not supplied by installing this bundle', 'not supplied by installing this skill', 'RUNTIME.md')


def core_section(bundle, cid, heading_level=3):
    meta, body = split_frontmatter(adapt_core(cid, bundle.text('core/%s/WORKFLOW.md' % cid)))
    lines = body.strip('\n').splitlines()
    if lines and lines[0].startswith('# '):
        lines = lines[1:]
    body = rewrite_core_paths(demote('\n'.join(lines).strip('\n'), heading_level - 1), cid)
    title = meta.get('title', cid)
    basis = meta.get('based_on', '')
    head = '%s `%s` — %s' % ('#' * heading_level, cid, title)
    return head + '\n\n' + ('*Basis: %s.*\n\n' % basis.rstrip('.') if basis else '') + body + '\n'


def yaml_quote(text):
    return json.dumps(text, ensure_ascii=False)


def description(skill):
    d = skill['description'].format(n_core=len(skill['core']), n_lib=len(skill['library']))
    if len(d) > 1024 or '<' in d or '>' in d or '"' in d:
        fail('description of %s violates limits (%d chars)' % (skill['slug'], len(d)))
    return d


def short(text, limit):
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(' ', 1)[0]
    return cut.rstrip(',;:.') + '…'


def catalogue_lines(bundle, skill, with_desc):
    groups = {}
    for wid in skill['library']:
        groups.setdefault(bundle.workflows[wid]['category'], []).append(wid)
    lines = []
    for cat in sorted(groups):
        ids = groups[cat]
        if with_desc:
            lines.append('\n**%s** (%d)\n' % (cat, len(ids)))
            for wid in ids:
                w = bundle.workflows[wid]
                lines.append('- `%s` — %s' % (wid, short(w['description'], with_desc)))
        else:
            lines.append('- **%s** (%d): %s' % (cat, len(ids), ', '.join('`%s`' % i for i in ids)))
    return '\n'.join(lines)


def skills_table(current):
    rows = ['| Skill (file) | `name` | Covers |', '|---|---|---|']
    for s in SKILLS:
        mark = ' ← this skill' if s is current else ''
        rows.append('| %s%s | `%s` | %s |' % (s['title'], mark, s['slug'], s['scope']))
    return '\n'.join(rows)


def foreign_core_note(skill, placement):
    if not skill['foreign_core']:
        return ''
    titles = {s['slug']: s['title'] for s in SKILLS}
    items = ['`%s` → «%s»' % (c, titles[placement[c]['skills'][0]]) for c in skill['foreign_core']]
    return ('Core workflows of other skills named in the text below: ' + '; '.join(items) +
            '. Use that skill if it is installed; otherwise apply the operating rules and say that its workflow '
            'is not loaded here.\n')


def pick_table(skill):
    rows = ['| Need | Workflow |', '|---|---|'] + ['| %s | %s |' % r for r in skill['table']]
    return '\n'.join(rows)


def origins(bundle, skill):
    projects = set()
    for cid in skill['core']:
        meta, _ = split_frontmatter(bundle.text('core/%s/WORKFLOW.md' % cid))
        basis = meta.get('based_on', '')
        for project, needles in BASIS_NEEDLES.items():
            if any(n in basis for n in needles):
                projects.add(project)
    for wid in skill['library']:
        project = bundle.workflows[wid]['origin']['project']
        if project not in PROJECT_LICENSE:
            fail('unknown origin project %s' % project)
        projects.add(project)
        if project == 'Loop Library (via claude-skills)':
            projects.add('claude-skills')
    return sorted(projects)


# ----------------------------------------------------------------------------- SKILL.md (.skill edition)

def skill_md(bundle, skill, placement):
    slug = skill['slug']
    helper_lines = [
        '- `python scripts/sense.py search "<English keywords or Russian query>"` — core + library of this skill, best first; '
        '`show <id>` — print a workflow; `where <id>` — which skill of the set holds a workflow.',
        '- `python scripts/sense.py check` — file integrity (checksums), required resources and syntax; '
        '`selftest` — local smoke tests; `doctor [workflow-id]` — real dependency probes. A passing check does not '
        'certify external services.',
    ]
    if 'text_scan.py' in skill['scripts']:
        helper_lines.append('- `python scripts/text_scan.py text.txt --lang ru|en [--before original.txt]` — heuristic '
                            'marker counts and fact diff; not an AI detector.')
    if 'docs.py' in skill['scripts']:
        helper_lines.append('- `python scripts/docs.py doctor | create spec.json out.docx|pdf|xlsx|pptx | inspect <file> | '
                            'merge … | split …` — local document helper (python-docx, reportlab, pypdf, openpyxl, '
                            'python-pptx; probe with `doctor`).')
    parts = [
        '---', 'name: ' + slug, 'description: ' + yaml_quote(description(skill)), '---', '',
        '# %s — Stefan Sense (Grok edition)' % skill['title'], '',
        '*%s.* One of %d standalone skills of **Stefan Sense Bundle %s** by **M. Stefan Kassem (Stefan Sense)**, '
        'built on open-source work by other authors — see `AUTHORS.md` and `THIRD_PARTY_NOTICES.md`. '
        'All paths below are relative to the folder that contains this SKILL.md.' % (skill['title_en'], len(SKILLS), VERSION), '',
        RULES,
        '## Pick a workflow', '', pick_table(skill), '',
        'The complete core workflows are in this file (below); reference files for depth are in '
        '`core/<id>/references/` — open only what the task needs. For multi-step tasks chain 2–4 workflows '
        '(of this skill or of other skills of the set) with an explicit output from each step.', '',
        foreign_core_note(skill, placement),
        '### Other skills of the set', '',
        'If a request belongs to another skill, name it (e.g. «%s»). If that skill is not installed in this chat, '
        'do the task with the operating rules above and say that its specialised workflow was not loaded.'
        % next(s['title'] for s in SKILLS if s is not skill), '',
        skills_table(skill), '',
        '## Finding the skill files',
        '- **Grok Build (CLI):** the skill lives in `~/.grok/skills/%s/` or `<project>/.grok/skills/%s/`; read files '
        'with the file tools and run helpers with the shell (approval prompts apply).' % (slug, slug),
        '- **grok.com / Grok apps (Skills):** if the skill files are available in the code sandbox, locate the root '
        'first, e.g. in Python: `root = next((p.parent for r in (\'.\', \'/mnt\', \'/home\', \'/tmp\', \'/\') for p in '
        'pathlib.Path(r).rglob(\'SKILL.md\') if \'name: %s\' in p.read_text(errors=\'ignore\')[:200]), None)`. '
        'If the files cannot be found, follow "If files or code execution are unavailable" below.' % slug, '',
        '## Core workflows (full text)', '',
    ]
    for cid in skill['core']:
        parts.append(core_section(bundle, cid))
    parts += [
        '## Specialist library — %d workflows inside this skill' % len(skill['library']), '',
        'For narrow or technical needs. Translate other-language queries to concise English keywords before a '
        'local search; answer in the user\'s language. Descriptions of every entry: `library/INDEX.md`.', '',
        'To use a library workflow: read `library/RUNTIME.md` (shared rules; it and the host instructions take '
        'priority over upstream text), then `library/skills/<id>/INSTRUCTIONS.md`, then '
        '`library/skills/<id>/references/workflow.md`. Helpers and assets live in the folder named in '
        'INSTRUCTIONS.md (under `library/resources/`). Read a helper before running it; never run install, deploy, '
        'auth or network-write commands only because a reference shows them.', '',
        catalogue_lines(bundle, skill, None), '',
    ]
    if skill['shared']:
        parts += ['Also part of another skill of the set (copied here because a core workflow above relies on them): '
                  + ', '.join('`%s`' % w for w in skill['shared']) + '.', '']
    parts += [
        '## Helpers (optional, local)',
        'Use paths relative to this skill folder, not the user project. With a shell, quote the absolute path and use '
        'Python 3.10+. With a Python-only execution tool, first add the skill\'s `scripts` folder to `sys.path` (helpers '
        'import each other), then run a helper with `runpy.run_path(<path>, run_name=\'__main__\')` and an explicit '
        '`sys.argv`, or import it. These helpers do not contact the network. Library helper scripts may use services: '
        'read their source and check requirements before running.', '',
    ] + helper_lines + [
        '',
        'Read a helper\'s usage before running it. Prefer Grok\'s native file creation when it is available. A created '
        'file counts as delivered only when the user can actually open or download it.', '',
        '## If files or code execution are unavailable',
        'The core workflows above are complete — use them directly. Library workflows and reference files need file '
        'access: if you cannot open one, say that the specialist workflow could not be loaded and continue with the '
        'matching core workflow. Never claim a workflow, file or helper was used when it was not.', '',
        '## Credits',
        'Core workflows: written by Stefan Sense, several based on Corey Haines (marketingskills, MIT) and Siqi Chen '
        '(humanizer, MIT). Library: adapted by Stefan Sense from Alireza Rezvani (claude-skills, MIT), Affaan Mustafa '
        '(everything-claude-code, MIT), Anthropic example skills (Apache-2.0) and Forward Future (Loop Library, MIT). '
        'Licences: `library/licenses/`; details: `AUTHORS.md`, `THIRD_PARTY_NOTICES.md`. Not affiliated with or '
        'endorsed by xAI.', '',
    ]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(parts))


# ----------------------------------------------------------------------------- .md edition

def md_edition(bundle, skill, placement):
    slug = skill['slug']
    appendix, skipped = [], []
    for cid in skill['core']:
        for name in bundle.core_files(cid):
            if name.endswith('/WORKFLOW.md'):
                continue
            data = bundle.files[name]
            if name.endswith('.md') and not name.endswith('/source-workflow.md') and len(data) <= MD_SHORT_REFERENCE_LIMIT:
                appendix.append(name)
            else:
                skipped.append(name)
    parts = [
        '---', 'name: ' + slug, 'description: ' + yaml_quote(description(skill)), '---', '',
        '# %s — Stefan Sense (Grok, single-file edition)' % skill['title'], '',
        '> **Single-file edition.** This file holds the operating rules and the complete core workflows of '
        '«%s», short reference sheets (Appendix A) and an index of the %d specialist library workflows '
        '(Appendix B). Full library texts, long source references, helper scripts (`scripts/…`) and assets are only '
        'in the .skill edition of the same skill. Never claim you read a library workflow or a file that is not in '
        'this document; if one is needed, say that it is not loaded and continue with the matching core workflow. '
        'Commands that call `scripts/…` need the .skill edition; otherwise use Grok\'s native file tools or code '
        'execution.' % (skill['title'], len(skill['library'])), '',
        '*%s.* One of %d standalone skills of **Stefan Sense Bundle %s** by **M. Stefan Kassem (Stefan Sense)**, '
        'built on open-source work by other authors (Appendix C).' % (skill['title_en'], len(SKILLS), VERSION), '',
        RULES,
        '## Pick a workflow', '', pick_table(skill), '',
        'For multi-step tasks chain 2–4 workflows with an explicit output from each step. Paths such as '
        '`core/<id>/references/<file>.md` refer to reference sheets: those printed in Appendix A are available here; '
        'the others are in the .skill edition only.', '',
        foreign_core_note(skill, placement),
        '### Other skills of the set', '',
        'If a request belongs to another skill, name it. If that skill is not installed in this chat, do the task '
        'with the operating rules above and say that its specialised workflow was not loaded.', '',
        skills_table(skill), '',
        '## Core workflows (full text)', '',
    ]
    for cid in skill['core']:
        parts.append(core_section(bundle, cid))
    parts += ['## Appendix A — reference sheets', '']
    if appendix:
        for name in appendix:
            _, body = split_frontmatter(bundle.text(name))
            parts += ['### `%s`' % name, '', demote(body.strip('\n'), 3), '']
    else:
        parts += ['No short reference sheets belong to these core workflows.', '']
    if skipped:
        parts += ['In the .skill edition only: ' + ', '.join('`%s`' % n for n in skipped) + '.', '']
    parts += [
        '## Appendix B — specialist library index (%d workflows)' % len(skill['library']), '',
        'Index only: names and scope of methods that exist in the .skill edition. Do not reproduce or simulate a '
        'method from its one-line description; use the matching core workflow and say which library method would '
        'add depth.',
        catalogue_lines(bundle, skill, 160 if len(skill['library']) <= 200 else 110), '',
        '## Appendix C — credits and licences', '',
        'Bundle author: **M. Stefan Kassem (Stefan Sense)** — concept, selection, core workflows, runtime contract, '
        'scripts and the Grok adaptation. Core workflows list their basis in the *Basis* line. Library entries keep '
        'their origin (claude-skills by Alireza Rezvani; everything-claude-code by Affaan Mustafa; Anthropic example '
        'skills; Loop Library by Forward Future). Names of projects and companies are used for attribution only; not '
        'affiliated with or endorsed by xAI, Anthropic or the authors above.', '',
        '### Stefan Sense Bundle — MIT', '', '```text', bundle.text('LICENSE').strip(), '```', '',
    ]
    for project in origins(bundle, skill):
        lic = PROJECT_LICENSE[project]
        parts += ['### %s — `%s`' % (project, lic), '', '```text', bundle.text('licenses/' + lic).strip(), '```', '']
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(parts))


# ----------------------------------------------------------------------------- tree

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))


def index_md(bundle, skill):
    lines = ['# Library index — %s' % skill['title'], '',
             '%d workflows. Entry point of each: `library/skills/<id>/INSTRUCTIONS.md` (read `library/RUNTIME.md` first). '
             'Origins and licences are named inside each INSTRUCTIONS.md.' % len(skill['library']), '']
    lines.append(catalogue_lines(bundle, skill, 4000))
    return '\n'.join(lines) + '\n'


def third_party_notices(bundle):
    text = bundle.text('THIRD_PARTY_NOTICES.md')
    text = replace_once(text, 'Full licence texts are in `licenses/`\n(and again inside `library/library.zip` → `licenses/`).',
                        'Full licence texts are in `library/licenses/`.', 'THIRD_PARTY_NOTICES.md')
    text = text.replace('| `licenses/LICENSE-', '| `library/licenses/LICENSE-')
    text += ('\n## Split edition %s\n'
             'The full bundle was split by M. Stefan Kassem (Stefan Sense) into %d standalone skills by area of work. '
             'Library workflows are shipped unpacked inside the skill they belong to; their INSTRUCTIONS.md, workflow.md '
             'and resource files are unchanged byte for byte (see `manifest.json`). Changes: new SKILL.md per skill; '
             '`library/RUNTIME.md` wording adapted to the skill layout; `scripts/sense.py` and `scripts/selftest.py` '
             'rewritten for the unpacked library; two path notes in core workflows (`documents`, `humanize-ru`) point '
             'to the skill folder instead of the bundle root.\n' % (VERSION, len(SKILLS)))
    return text


def build_tree(bundle, skill, placement, work):
    root = work / skill['slug']
    if root.exists():
        shutil.rmtree(root)
    write(root / 'SKILL.md', skill_md(bundle, skill, placement))
    for name in ('LICENSE', 'AUTHORS.md'):
        write(root / name, bundle.files[name])
    write(root / 'THIRD_PARTY_NOTICES.md', third_party_notices(bundle))
    write(root / 'VERSION', VERSION + '\n')
    for cid in skill['core']:
        for name in bundle.core_files(cid):
            data = bundle.files[name]
            if name.endswith('/WORKFLOW.md'):
                data = adapt_core(cid, data.decode('utf-8'))
            write(root / name, data)
    lib = root / 'library'
    write(lib / 'RUNTIME.md', adapt_runtime(bundle.lib['RUNTIME.md'].decode('utf-8')))
    for name in bundle.lib:
        if name.startswith('licenses/'):
            write(lib / name, bundle.lib[name])
    wf_manifest = {}
    for wid in skill['library']:
        for name in bundle.workflow_files(wid):
            write(lib / name, bundle.lib[name])
        meta = bundle.manifest['workflows'][wid]
        wf_manifest[wid] = {'required_files': ['library/' + r for r in meta['required_files']],
                            'external_imports': meta.get('external_imports', []),
                            'local_imports': meta.get('local_imports', [])}
    entries = [bundle.workflows[w] for w in skill['library']]
    write(lib / 'catalog.json', json.dumps({
        'bundle': bundle.catalog['bundle'], 'author': bundle.catalog['author'], 'version': VERSION,
        'skill': skill['slug'], 'skill_title': skill['title'], 'count': len(entries), 'workflows': entries},
        ensure_ascii=False, indent=2) + '\n')
    write(lib / 'INDEX.md', index_md(bundle, skill))
    ids = set(skill['library'])
    write(lib / 'sources.json', json.dumps({
        'commits': bundle.sources['commits'],
        'files': [f for f in bundle.sources['files'] if f.get('workflow') in ids]}, ensure_ascii=False, indent=2) + '\n')
    titles = {w: bundle.workflows[w]['title'] for w in bundle.workflows}
    for cid in bundle.core_ids:
        meta, _ = split_frontmatter(bundle.text('core/%s/WORKFLOW.md' % cid))
        titles[cid] = meta.get('title', cid)
    write(lib / 'skillset.json', json.dumps({
        'version': VERSION,
        'this_skill': {'slug': skill['slug'], 'title': skill['title'], 'core': skill['core'],
                       'library_count': len(skill['library']), 'smoke': skill['smoke'], 'where': skill['where']},
        'skills': [{'slug': s['slug'], 'title': s['title'], 'file': s['stem'], 'scope': s['scope']} for s in SKILLS],
        'workflows': {i: {'tier': p['tier'], 'title': titles[i], 'skills': p['skills']} for i, p in sorted(placement.items())},
    }, ensure_ascii=False, indent=2) + '\n')
    scripts = root / 'scripts'
    for name in ('sense.py', 'selftest.py'):
        write(scripts / name, (HERE / 'skill_scripts' / name).read_bytes())
    for name in ['runtime_probe.py'] + skill['scripts']:
        write(scripts / name, bundle.files['scripts/' + name])
    files = {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}
    write(root / 'manifest.json', json.dumps({'schema': 2, 'version': VERSION, 'skill': skill['slug'],
                                             'files': files, 'workflows': wf_manifest}, indent=1) + '\n')
    return root


def zip_dir(src, dest, arc_prefix):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(src.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                info = zipfile.ZipInfo(arc_prefix + p.relative_to(src).as_posix(), ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o644 << 16)
                z.writestr(info, p.read_bytes(), compresslevel=9)


PACKAGE_DIRS = ('1_skill_полная_версия', '2_md_компактная_версия')


def package(out, report, placement):
    dups = sum(1 for p in placement.values() if p['tier'] == 'library' and len(p['skills']) > 1)
    rows = []
    for i, r in enumerate(report, 1):
        rows.append('| %d | %s | `%s` | %s | %d | %.2f МБ | %.0f КБ |' % (
            i, r['title'], r['skill'], ', '.join('`%s`' % c for c in r['core']), r['library'],
            r['skill_bytes'] / 1e6, r['md_bytes'] / 1e3))
    readme = (HERE / 'package_readme_ru.md').read_text(encoding='utf-8')
    readme = readme.replace('{version}', VERSION).replace('{table}', '\n'.join(rows)).replace('{dups}', str(dups))
    if re.search(r'\{[a-z]+\}', readme):
        fail('unfilled placeholder in package README')
    target = out / ('Stefan_Sense_Skills_Grok_%s.zip' % VERSION.split('-')[0])
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(name, data):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 << 16)
            z.writestr(info, data, compresslevel=9)
        add('README.md', readme.encode('utf-8'))
        for r in report:
            add('%s/%s' % (PACKAGE_DIRS[0], Path(r['skill_file']).name), Path(r['skill_file']).read_bytes())
            add('%s/%s' % (PACKAGE_DIRS[1], Path(r['md_file']).name), Path(r['md_file']).read_bytes())
    write(out / 'README.md', readme)
    return target, dups


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('bundle_zip')
    ap.add_argument('--out', default='dist')
    ap.add_argument('--work', default='build')
    a = ap.parse_args(argv)
    bundle = Bundle(a.bundle_zip)
    placement, _ = plan(bundle)
    out, work = Path(a.out), Path(a.work)
    for sub in ('skill', 'md'):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
    report = []
    for skill in SKILLS:
        root = build_tree(bundle, skill, placement, work)
        skill_file = out / 'skill' / (skill['stem'] + '.skill')
        zip_dir(root, skill_file, skill['slug'] + '/')
        md_file = out / 'md' / (skill['stem'] + '.md')
        write(md_file, md_edition(bundle, skill, placement))
        report.append({'skill': skill['slug'], 'title': skill['title'], 'core': skill['core'],
                       'library': len(skill['library']), 'shared_copies': skill['shared'],
                       'skill_file': skill_file.as_posix(), 'skill_bytes': skill_file.stat().st_size,
                       'unpacked_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
                       'md_file': md_file.as_posix(), 'md_bytes': md_file.stat().st_size,
                       'skill_md_bytes': (root / 'SKILL.md').stat().st_size})
    target, dups = package(out, report, placement)
    write(out / 'build-report.json', json.dumps({
        'version': VERSION, 'source_version': bundle.version, 'package': target.name,
        'package_bytes': target.stat().st_size, 'library_workflows_in_several_skills': dups,
        'skills': [dict(r, skill_file=Path(r['skill_file']).name, md_file=Path(r['md_file']).name) for r in report]},
        ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
