"""Durable word notebooks, recall scheduling, dictionary cache, and debate practice."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener

from .copilot import _NoRedirect, _text
from .lexicon import browse_offline, data_directory, offline_lookup

SEED_PATH = Path(__file__).parent / "data" / "vocabulary.json"
COLLECTIONS_PATH = Path(__file__).parent / 'data' / 'vocabulary_collections.json'
CATEGORY_ALIASES = {'Reasoning': 'Debate & reasoning', 'Evidence': 'Evidence & research',
                    'Precision': 'Precise wording', 'Listening': 'Communication & listening',
                    'Policy': 'Policy & ethics'}
DAY = 86400
INTERVALS = (1, 3, 7, 14, 30, 60, 120)
CONTENT_FIELDS = {
    "word": 80,
    "definition": 1800,
    "example": 900,
    "root": 500,
    "family": 500,
    "own_words": 1500,
    "own_example": 1500,
    "context": 2000,
    "source_title": 200,
    "source_url": 1000,
    "theme": 80,
    "level": 30,
    "part_of_speech": 40,
}


class VocabularyConflict(ValueError):
    """A stale save or duplicate review must not overwrite current progress."""


def normalize_word(value: object) -> str:
    word = _text(value, "word", 80, required=True).casefold()
    if not any(c.isalpha() for c in word) or any(not (c.isalpha() or c in " '-") for c in word):
        raise ValueError("Use a word or phrase containing letters, spaces, apostrophes or hyphens.")
    return " ".join(word.split())


def safe_url(value: object) -> str:
    value = _text(value, "source URL", 1000)
    if value and (urlparse(value).scheme not in ("http", "https") or not urlparse(value).netloc):
        raise ValueError("Source links must be HTTP or HTTPS URLs.")
    return value


def _integer(value: object, name: str, upper: int) -> int:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f"{name} must be an integer from 0 to {upper}")
    return value


def validate_card(data: dict, *, progress: bool = False) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Each word must be an object")
    card = {name: _text(data.get(name, ""), name, limit) for name, limit in CONTENT_FIELDS.items()}
    card["word"] = normalize_word(card["word"])
    if not card["definition"]:
        raise ValueError("A definition is required")
    card["source_url"] = safe_url(card["source_url"])
    source = data.get("attribution", {})
    if not isinstance(source, dict):
        raise ValueError("attribution must be an object")
    card["attribution"] = {
        key: _text(source.get(key, ""), key, 1000)
        for key in ("name", "url", "license", "license_url", "note")
    }
    for key in ("url", "license_url"):
        card["attribution"][key] = safe_url(card["attribution"][key])
    focus = data.get("focus", False)
    if type(focus) is not bool:
        raise ValueError("focus must be true or false")
    card["focus"] = focus
    card.update(box=0, due=0, reviews=0, lapses=0, revision=0)
    if progress:
        for name, upper in (
            ("box", 6),
            ("due", 4102444800),
            ("reviews", 1000000),
            ("lapses", 1000000),
            ("revision", 1000000),
        ):
            card[name] = _integer(data.get(name, 0), name, upper)
    return card


def fetch_dictionary(word: str) -> dict:
    """One bounded request to an explicit public provider; only the word is sent."""
    url = "https://freedictionaryapi.com/api/v1/entries/en/" + quote(word, safe="")
    request = Request(
        url, headers={"Accept": "application/json", "User-Agent": "ProSe-Vocabulary/1.0"}
    )
    with build_opener(_NoRedirect()).open(request, timeout=4) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Dictionary response too large")
    data = json.loads(raw)
    senses, pronunciation = [], ""
    for entry in data["entries"][:12]:
        if entry.get("language", {}).get("code") != "en":
            continue
        if not pronunciation:
            pronunciation = next(
                (
                    p["text"][:200]
                    for p in entry.get("pronunciations", [])
                    if isinstance(p.get("text"), str)
                ),
                "",
            )
        for sense in entry.get("senses", [])[:8]:
            definition = _text(sense.get("definition", ""), "definition", 10000)
            if definition:
                examples = sense.get("examples", [])
                senses.append(
                    {
                        "definition": definition[:1800],
                        "example": next((s[:900] for s in examples if isinstance(s, str)), ""),
                        "part_of_speech": entry.get("partOfSpeech", "")[:40],
                        "synonyms": [
                            s[:80] for s in sense.get("synonyms", []) if isinstance(s, str)
                        ][:8],
                    }
                )
    if not senses:
        raise ValueError("No English definitions returned")
    source = data["source"]
    return {
        "word": word,
        "senses": senses[:8],
        "pronunciation": pronunciation,
        "source": {
            "name": "Wiktionary via FreeDictionaryAPI.com",
            "url": safe_url(source.get("url", "")),
            "license": _text(source["license"]["name"], "license", 100),
            "license_url": safe_url(source["license"]["url"]),
            "note": "Selected senses reformatted for this word notebook.",
        },
        "availability": "online dictionary",
    }


class VocabularyStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or data_directory()).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "vocabulary.sqlite3"
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS words (word TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dictionary_cache
                    (word TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS usages
                    (event TEXT NOT NULL, word TEXT NOT NULL, stamp INTEGER NOT NULL,
                     PRIMARY KEY(event, word));
            """)
            connection.execute("BEGIN IMMEDIATE")
            seeded = connection.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone()
            if not seeded:
                for item in json.loads(SEED_PATH.read_text(encoding="utf-8"))["words"]:
                    card = validate_card(item)
                    connection.execute(
                        "INSERT OR IGNORE INTO words VALUES (?, ?)",
                        (card["word"], json.dumps(card)),
                    )
                connection.execute("INSERT INTO settings VALUES ('seeded', 'true')")
                connection.execute("INSERT OR IGNORE INTO settings VALUES ('online', 'true')")
            expanded = connection.execute(
                "SELECT 1 FROM settings WHERE key='collections-v1'").fetchone()
            if not expanded:
                capacity = 5000 - connection.execute('SELECT COUNT(*) FROM words').fetchone()[0]
                for item in json.loads(COLLECTIONS_PATH.read_text(encoding='utf-8'))['words']:
                    if capacity <= 0:
                        break
                    card = validate_card(item)
                    inserted = connection.execute(
                        'INSERT OR IGNORE INTO words VALUES (?, ?)',
                        (card['word'], json.dumps(card))).rowcount
                    capacity -= inserted
                connection.execute("INSERT INTO settings VALUES ('collections-v1', 'true')")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def listing(self) -> dict:
        now = int(time.time())
        with self.connection() as connection:
            cards = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM words")]
            row = connection.execute("SELECT value FROM settings WHERE key='online'").fetchone()
            counts = dict(connection.execute("SELECT word, COUNT(*) FROM usages GROUP BY word"))
        cards.sort(key=lambda card: (card["due"], card["word"]))
        for card in cards:
            card["uses"] = counts.get(card["word"], 0)
            card['category'] = CATEGORY_ALIASES.get(card['theme'], card['theme']) or 'Your words'
        categories = sorted({card['category'] for card in cards})
        return {
            "words": cards,
            "due": sum(card["due"] <= now for card in cards),
            "online": row is None or row[0] == "true",
            "now": now,
            "offline_dictionary": (self.directory / "wordnet.sqlite3").exists(),
            "scheduler": "Leitner: 1, 3, 7, 14, 30, 60, 120 days",
            'categories': categories,
            'category_counts': {name: sum(c['category'] == name for c in cards)
                                for name in categories},
        }

    def library(self, data: dict) -> dict:
        return browse_offline(self.directory, data.get('query', ''), data.get('offset', 0))

    def save(self, data: dict) -> dict:
        card = validate_card(data)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM words WHERE word=?", (card["word"],)
            ).fetchone()
            if row:
                previous = json.loads(row[0])
                if (
                    type(data.get("revision")) is not int
                    or data["revision"] != previous["revision"]
                ):
                    raise VocabularyConflict("This word changed. Reload it before saving again.")
                for key in ("box", "due", "reviews", "lapses"):
                    card[key] = previous[key]
                card["revision"] = previous["revision"] + 1
            elif connection.execute("SELECT COUNT(*) FROM words").fetchone()[0] >= 5000:
                raise ValueError(
                    "Notebook limit is 5,000 words. Export it before creating another."
                )
            connection.execute(
                "INSERT OR REPLACE INTO words VALUES (?, ?)", (card["word"], json.dumps(card))
            )
        return card

    def review(self, data: dict) -> dict:
        word = normalize_word(data.get("word"))
        rating = data.get("rating")
        if rating not in ("again", "hard", "good", "easy"):
            raise ValueError("Choose Again, Hard, Good or Easy.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM words WHERE word=?", (word,)).fetchone()
            if row is None:
                raise KeyError("Word not found")
            card = json.loads(row[0])
            if type(data.get("revision")) is not int or data["revision"] != card["revision"]:
                raise VocabularyConflict("This review was already saved. Load the next card.")
            card["own_words"] = _text(data.get("own_words", card["own_words"]), "own words", 1500)
            card["own_example"] = _text(
                data.get("own_example", card["own_example"]), "example", 1500
            )
            box = card["box"]
            if rating == "again":
                card["box"] = 0
                seconds = 600
                card["lapses"] += 1
            elif rating == "hard":
                card["box"] = max(0, box - 1)
                seconds = DAY
            else:
                advance = 1 if rating == "good" else 2
                seconds = INTERVALS[min(6, box + advance - 1)] * DAY
                card["box"] = min(6, box + advance)
            card["due"] = int(time.time()) + seconds
            card["reviews"] += 1
            card["revision"] += 1
            connection.execute("UPDATE words SET payload=? WHERE word=?", (json.dumps(card), word))
        return card

    def settings(self, data: dict) -> dict:
        online = data.get("online")
        if type(online) is not bool:
            raise ValueError("online must be true or false")
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO settings VALUES ('online', ?)", (json.dumps(online),)
            )
        return {"online": online}

    def lookup(self, value: object) -> dict:
        word = normalize_word(value)
        with self.connection() as connection:
            cached = connection.execute(
                "SELECT payload, fetched FROM dictionary_cache WHERE word=?", (word,)
            ).fetchone()
            setting = connection.execute("SELECT value FROM settings WHERE key='online'").fetchone()
        online = setting is None or setting[0] == "true"
        if cached and (not online or int(time.time()) - cached[1] < 30 * DAY):
            return {**json.loads(cached[0]), "availability": "saved dictionary lookup"}
        if online:
            try:
                result = fetch_dictionary(word)
                with self.connection() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO dictionary_cache VALUES (?, ?, ?)",
                        (word, json.dumps(result), int(time.time())),
                    )
                return result
            except (URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        if cached:
            return {**json.loads(cached[0]), "availability": "offline cached lookup"}
        offline = offline_lookup(word, self.directory)
        if offline:
            return offline
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM words WHERE word=?", (word,)).fetchone()
        if row:
            card = json.loads(row[0])
            return {
                "word": word,
                "senses": [
                    {
                        "definition": card["definition"],
                        "example": card["example"],
                        "part_of_speech": card["part_of_speech"],
                        "synonyms": [],
                    }
                ],
                "source": card["attribution"],
                "pronunciation": "",
                "availability": "saved word notebook",
            }
        raise ValueError(
            "No saved or offline definition found. Add your own definition or try online later."
        )

    def focus_words(self) -> list[dict]:
        cards = self.listing()["words"]
        return [
            {key: card[key] for key in ("word", "definition", "example")}
            for card in cards
            if card["focus"]
        ][:3]

    def record_usage(self, event: str, text: str, words: list[dict]) -> list[str]:
        used = [
            item["word"]
            for item in words
            if re.search(r"(?<!\w)" + re.escape(item["word"]) + r"(?!\w)", text, re.I)
        ]
        with self.connection() as connection:
            for word in used:
                connection.execute(
                    "INSERT OR IGNORE INTO usages VALUES (?, ?, ?)", (event, word, int(time.time()))
                )
        return used

    def export(self) -> dict:
        listing = self.listing()
        with self.connection() as connection:
            usages = [
                list(row) for row in connection.execute("SELECT event, word, stamp FROM usages")
            ]
        return {
            "format": "prose-vocabulary",
            "version": 1,
            "words": listing["words"],
            "online": listing["online"],
            "usages": usages,
        }

    def import_backup(self, data: dict) -> dict:
        if data.get("format") != "prose-vocabulary" or data.get("version") != 1:
            raise ValueError("Choose a ProSe vocabulary JSON backup (version 1).")
        words = data.get("words")
        if not isinstance(words, list) or len(words) > 5000:
            raise ValueError("Backup must contain at most 5,000 words.")
        cards = [validate_card(card, progress=True) for card in words]
        if len({card["word"] for card in cards}) != len(cards):
            raise ValueError("Backup contains duplicate words.")
        usages = data.get("usages", [])
        if not isinstance(usages, list) or len(usages) > 100000:
            raise ValueError("Invalid usage history")
        checked = []
        for row in usages:
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError("Invalid usage record")
            checked.append(
                (
                    _text(row[0], "event", 100, required=True),
                    normalize_word(row[1]),
                    _integer(row[2], "usage date", 4102444800),
                )
            )
        # A pristine starter card can be restored; user-edited cards are kept.
        pristine = {
            item["word"]: validate_card(item)
            for path in (COLLECTIONS_PATH, SEED_PATH)
            for item in json.loads(path.read_text(encoding="utf-8"))["words"]
        }
        added = 0
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                row[0]: json.loads(row[1])
                for row in connection.execute("SELECT word, payload FROM words")
            }
            if len(set(existing) | {card["word"] for card in cards}) > 5000:
                raise ValueError("Import would exceed the 5,000-word notebook limit.")
            for card in cards:
                word = card["word"]
                if word not in existing or existing[word] == pristine.get(word):
                    connection.execute(
                        "INSERT OR REPLACE INTO words VALUES (?, ?)", (word, json.dumps(card))
                    )
                    added += 1
            connection.executemany("INSERT OR IGNORE INTO usages VALUES (?, ?, ?)", checked)
        return {"added": added, "kept_existing": len(cards) - added}

    def anki_text(self) -> str:
        lines = ["#separator:Tab", "#html:false", "#columns:Front\tBack"]
        for card in self.listing()["words"]:
            source = card["attribution"]
            back = " | ".join(
                filter(
                    None,
                    (
                        card["definition"],
                        card["example"],
                        card["root"],
                        card["family"],
                        card["own_words"],
                        source["name"],
                        source["url"],
                        source["license"],
                        source["license_url"],
                    ),
                )
            )
            lines.append(card["word"] + "\t" + re.sub(r"[\t\r\n]+", " ", back))
        return "\n".join(lines) + "\n"
