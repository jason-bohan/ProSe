"""Rebuild themed study cards from the installed, licensed WordNet snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from prose.lexicon import WORDNET_SHA256, data_directory, offline_lookup
from prose.vocabulary import normalize_word, validate_card

ROOT = Path(__file__).resolve().parents[1]
COURT_URL = 'https://www.uscourts.gov/glossary'


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(value)
    return ' '.join(''.join(parser.parts).split())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--court-html', type=Path, required=True,
                        help='Saved US Courts glossary HTML snapshot')
    args = parser.parse_args()
    spec = json.loads((ROOT / 'prose/data/vocabulary_collection_words.json').read_text())
    words, seen, missing = [], set(), []
    for collection in spec['collections']:
        if collection['title'] == 'Law & procedure':
            continue  # Legal senses come from the federal judiciary's glossary below.
        for entry in collection['words'].split(', '):
            word, _, hint = entry.partition('|')
            if word in seen:
                continue
            result = offline_lookup(word, data_directory())
            if not result:
                missing.append(word)
                continue
            senses = result['senses']
            sense = next((s for s in senses if hint in s['definition'].casefold()), None)
            if not sense:
                missing.append(entry + ' (sense mismatch)')
                continue
            seen.add(word)
            card = validate_card({
                'word': word, 'definition': sense['definition'], 'example': sense['example'],
                'part_of_speech': sense['part_of_speech'], 'theme': collection['title'],
                'level': collection['level'], 'attribution': result['source'],
                'source_title': result['source']['name'], 'source_url': result['source']['url'],
                'context': 'Dictionary study sense. Choose another sense with dictionary lookup '
                           'if needed. Write your own debate example.'})
            words.append(card)
    if missing:
        print(json.dumps({'missing': missing}, indent=2))
        raise SystemExit('Resolve missing words or senses before building the collection.')
    court_html = args.court_html.read_bytes()
    court_words, skipped = [], []
    for term, definition in re.findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>',
                                      court_html.decode('utf-8'), re.S):
        term = re.sub(r'\s*\([^)]*\)', '', plain(term)).strip()
        try:
            word = normalize_word(term)
        except ValueError:
            skipped.append(term)
            continue
        attribution = {
            'name': 'Administrative Office of the U.S. Courts · Glossary of Legal Terms',
            'url': COURT_URL, 'license': 'U.S. federal government work (public domain in U.S.)',
            'license_url': 'https://www.usa.gov/government-copyright',
            'note': 'Federal-court glossary, retrieved 2026-10-01. Whitespace normalized. '
                    'Study vocabulary; jurisdiction and current governing law still matter.'}
        card = validate_card({
            'word': word, 'definition': plain(definition), 'theme': 'Law & procedure',
            'level': 'Intermediate', 'attribution': attribution,
            'source_title': attribution['name'], 'source_url': COURT_URL,
            'context': 'Federal-court terminology. Write your own sentence and compare '
                       'the applicable rule before using this term in a legal argument.'})
        court_words.append(card)
    if len(court_words) < 100:
        raise SystemExit('Glossary parse appears incomplete; refusing to replace the collection.')
    court_set = {card['word'] for card in court_words}
    words = [card for card in words if card['word'] not in court_set] + court_words
    target = ROOT / 'prose/data/vocabulary_collections.json'
    target.write_text(json.dumps({
        'format': 'prose-vocabulary', 'version': 1, 'collection_version': 1,
        'dictionary_sha256': WORDNET_SHA256,
        'court_glossary_sha256': hashlib.sha256(court_html).hexdigest(),
        'court_terms_skipped': skipped,
        'description': 'ProSe-selected themes and study levels. Definitions and available '
                       'examples from Open English WordNet 2025, CC BY 4.0; legal terms '
                       'from the U.S. Courts glossary. Not a current-law research service.',
        'words': words}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'cards': len(words), 'path': str(target)}))


if __name__ == '__main__':
    main()
