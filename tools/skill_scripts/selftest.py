"""Portable, offline smoke tests of ONE skill of the split Grok edition (temporary files only)."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))


def run():
    import sense
    here = Path(__file__).resolve().parent
    skill = sense.this_skill()
    passed, failed, skipped = [], [], []

    def check(name, fn):
        try:
            value = fn()
            if value is False: raise AssertionError('unexpected result')
            passed.append(name)
        except Exception as e:
            failed.append({'test': name, 'error': type(e).__name__ + ': ' + str(e)})

    def require(condition, label):
        if not condition: raise AssertionError(label)

    check('integrity check', lambda: require(sense.check()['status'] == 'ok', 'sense.py check reports problems'))
    check('core workflows readable', lambda: all(sense.show(w['id']) for w in sense.core_index()))

    def library_readable():
        for w in sense.library_items():
            p = sense.library_paths(w)
            require(p['instructions'].is_file() and p['workflow'].is_file(), 'missing entry point: ' + w['id'])
    check('library workflows readable', library_readable)
    if sense.library_items():
        first = sense.library_items()[0]['id']
        check('library show', lambda: 'Runtime contract' in sense.show(first))
    for query, expected in skill.get('smoke', []):
        check('search: ' + query, lambda q=query, e=expected: require(
            e in [r['id'] for r in sense.search(q)['results'][:3]], '%s not in top 3' % e))
    for ident, expected in skill.get('where', []):
        check('where: ' + ident, lambda i=ident, e=expected: require(
            e in [s['slug'] for s in sense.where(i)['skills']], 'wrong skill for ' + i))

    if (here / 'text_scan.py').exists():
        import text_scan
        check('English negation', lambda: bool(text_scan.diff("We don't sell data.", 'We sell data.', 'en')['removed_negations']))
        check('Curly apostrophe negation', lambda: bool(text_scan.diff('We don’t sell data.', 'We sell data.', 'en')['removed_negations']))
        check('Russian names', lambda: 'Пётр' in text_scan.diff('Иван оплатил.', 'Пётр оплатил.', 'ru')['added_capitalized_words'])
        check('numeric diff', lambda: text_scan.diff('До 15% не подтверждено.', '20% подтверждено.', 'ru')['removed_numbers'] == ['15%'])

    if (here / 'docs.py').exists():
        import docs
        with tempfile.TemporaryDirectory(prefix='sense-selftest-') as directory:
            out = Path(directory)
            spec = {'title': 'Проверка', 'subtitle': 'Подзаголовок', 'blocks': [{'type': 'paragraph', 'text': 'Сумма 42 сум.'}, {'type': 'table', 'headers': ['Товар', 'Цена'], 'rows': [['А', 42]]}, {'type': 'page_break'}, {'type': 'paragraph', 'text': 'Страница 2.'}]}

            def document():
                docs.create_docx(spec, str(out / 'test.docx'))
                data = docs.inspect_docx(str(out / 'test.docx'))
                require(data['tables'][0][1][1] == '42', 'table lost')

            def pdf():
                docs.create_pdf(spec, str(out / 'test.pdf'))
                data = docs.inspect_pdf(str(out / 'test.pdf')); require(data['pages'] == 2, 'wrong page count')
                require('Сумма 42' in data['text_by_page'][0], 'Cyrillic text lost')
                docs.merge_pdf([str(out / 'test.pdf')] * 2, str(out / 'merged.pdf'))
                require(len(docs.split_pdf(str(out / 'merged.pdf'), str(out / 'pages'))['outputs']) == 4, 'merge/split failed')

            def spreadsheet():
                docs.create_xlsx({'sheets': [{'name': 'Inputs', 'rows': [['Value'], [20]]}, {'name': 'Calc', 'rows': [['Total'], ['=Inputs!A2*2']]}, {'name': 'Text', 'formulas': False, 'rows': [['Text'], ['=literal']]}]}, str(out / 'test.xlsx'))
                data = docs.inspect_xlsx(str(out / 'test.xlsx'))
                require([s['formula_cells'] for s in data['sheets']] == [0, 1, 0], 'formula count incorrect')

            def presentation():
                docs.create_pptx({'title': 'Презентация', 'slides': [{'title': 'Таблица', 'layout': 'table', 'headers': ['Товар', 'Цена'], 'rows': [['А', 42]]}]}, str(out / 'test.pptx'))
                data = docs.inspect_pptx(str(out / 'test.pptx')); require(data['slides'][1]['tables'][0][1][1] == '42', 'table missing')
                require(not any(s['outside_slide'] for s in data['slides']), 'shape out of bounds')

            for name, modules, fn in [('DOCX', ['docx'], document), ('PDF merge/split', ['reportlab', 'pypdf'], pdf),
                                      ('XLSX', ['openpyxl'], spreadsheet), ('PPTX', ['pptx'], presentation)]:
                missing = [m for m in modules if importlib.util.find_spec(m) is None]
                if missing: skipped.append({'test': name, 'reason': 'missing ' + ', '.join(missing)})
                elif name.startswith('PDF') and not docs.find_font({}): skipped.append({'test': name, 'reason': 'Cyrillic TTF font not found'})
                else: check(name, fn)
            for ext, creator in docs.CREATORS.items():
                def invalid(creator=creator, ext=ext):
                    try: creator([], str(out / ('invalid' + ext)))
                    except docs.SpecError: return True
                    raise AssertionError('invalid spec accepted')
                check('spec validation ' + ext, invalid)

    return {'skill': skill['slug'], 'status': 'problems' if failed else 'partial' if skipped else 'ok',
            'passed': passed, 'failed': failed, 'skipped': skipped,
            'scope': 'Local smoke tests of this skill only; no network or external-service certification.'}


if __name__ == '__main__':
    result = run(); print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] in ('ok', 'partial') else 1)
