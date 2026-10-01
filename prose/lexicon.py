"""Install and query a licensed offline dictionary; no runtime package dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

WORDNET_URL = "https://en-word.net/static/english-wordnet-2025-json.zip"
WORDNET_SHA256 = "7d749f6e2c39e6970e4997839dcf6e42fd281f3c2fae0171d2192bae8cfa4b51"
WORDNET_SOURCE = {
    "name": "Open English WordNet 2025, derived from Princeton WordNet",
    "url": "https://en-word.net/",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "note": "Selected senses reformatted from the Open English WordNet Community release.",
}


def data_directory() -> Path:
    configured = os.getenv("PROSE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / ".prose"


def install_wordnet(archive: Path | None = None, directory: Path | None = None) -> dict:
    directory = directory or data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    downloaded = archive is None
    if downloaded:
        archive = directory / "english-wordnet-2025-json.zip"
        request = Request(WORDNET_URL, headers={"User-Agent": "ProSe-Vocabulary/1.0"})
        with urlopen(request, timeout=60) as response:
            content = response.read(16_000_001)
        if len(content) > 16_000_000:
            raise ValueError("Dictionary archive exceeded the size limit")
    else:
        content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != WORDNET_SHA256:
        raise ValueError("Dictionary checksum does not match the pinned 2025 release")
    if downloaded:
        archive.write_bytes(content)

    words: dict[str, list] = defaultdict(list)
    parts = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 150_000_000:
            raise ValueError("Expanded dictionary exceeded the size limit")
        for name in bundle.namelist():
            if name.startswith("entries-") or not name.endswith(".json"):
                continue
            for synset in json.loads(bundle.read(name)).values():
                if not isinstance(synset, dict):
                    continue
                definitions = synset.get("definition", [])
                members = synset.get("members", [])
                if not definitions or not members:
                    continue
                examples = synset.get("example", [])
                example = next((item for item in examples if isinstance(item, str)), "")
                for word in members:
                    word = word.casefold()
                    if len(word) > 80 or len(words[word]) >= 8:
                        continue
                    words[word].append(
                        {
                            "definition": definitions[0][:1800],
                            "example": example[:900],
                            "part_of_speech": parts.get(synset.get("partOfSpeech"), ""),
                            "synonyms": [item for item in members if item.casefold() != word][:8],
                        }
                    )
    if len(words) < 100_000:
        raise ValueError("Dictionary import appears incomplete")
    descriptor, temporary = tempfile.mkstemp(prefix="wordnet-", suffix=".sqlite3", dir=directory)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(temporary)) as connection, connection:
            connection.execute("CREATE TABLE lexicon (word TEXT PRIMARY KEY, senses TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO lexicon VALUES (?, ?)",
                ((word, json.dumps(senses)) for word, senses in words.items()),
            )
            connection.execute("CREATE TABLE metadata (value TEXT NOT NULL)")
            connection.execute("INSERT INTO metadata VALUES (?)", (json.dumps(WORDNET_SOURCE),))
        os.replace(temporary, directory / "wordnet.sqlite3")
    finally:
        Path(temporary).unlink(missing_ok=True)
    report = {"entries": len(words), "archive_sha256": WORDNET_SHA256, "source": WORDNET_SOURCE}
    (directory / "wordnet-attribution.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def offline_lookup(word: str, directory: Path) -> dict | None:
    path = directory / "wordnet.sqlite3"
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT senses FROM lexicon WHERE word = ?", (word,)).fetchone()
    if row is None:
        return None
    return {
        "word": word,
        "senses": json.loads(row[0]),
        "pronunciation": "",
        "source": {**WORDNET_SOURCE, "url": "https://en-word.net/view/lemma/" + quote(word)},
        "availability": "offline dictionary",
    }


def browse_offline(directory: Path, query: str = '', offset: int = 0) -> dict:
    """Paginated prefix browsing; no network request or bulk notebook import."""
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError('Library search must be at most 80 characters.')
    if type(offset) is not int or not 0 <= offset <= 200000:
        raise ValueError('Invalid library page.')
    path = directory / 'wordnet.sqlite3'
    if not path.exists():
        return {'installed': False, 'total': 0, 'matched': 0, 'words': [], 'offset': 0,
                'has_more': False, 'source': WORDNET_SOURCE}
    query = query.strip().casefold()
    # Escape SQL LIKE metacharacters so users search literal text.
    prefix = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        total = connection.execute('SELECT COUNT(*) FROM lexicon').fetchone()[0]
        matched = connection.execute("SELECT COUNT(*) FROM lexicon WHERE word LIKE ? ESCAPE '\\'",
                                     (prefix,)).fetchone()[0]
        rows = connection.execute(
            "SELECT word, senses FROM lexicon WHERE word LIKE ? ESCAPE '\\' "
            'ORDER BY word LIMIT 30 OFFSET ?', (prefix, offset)).fetchall()
    return {'installed': True, 'total': total, 'matched': matched, 'offset': offset,
            'has_more': offset + len(rows) < matched,
            'words': [{'word': word, 'senses': json.loads(senses)} for word, senses in rows],
            'source': WORDNET_SOURCE}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install the offline Open English WordNet dictionary"
    )
    parser.add_argument("--archive", type=Path, help="Use an already downloaded 2025 JSON ZIP")
    args = parser.parse_args()
    print(json.dumps(install_wordnet(args.archive), indent=2))


if __name__ == "__main__":
    main()
