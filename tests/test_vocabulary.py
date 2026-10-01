from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from prose.debate import COACH_PROMPT, DebateConfig, DebateSession
from prose.lexicon import install_wordnet
from prose.vocabulary import (
    VocabularyConflict,
    VocabularyStore,
    normalize_word,
)
from prose.web import build_site


@pytest.fixture
def notebook(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSE_DATA_DIR", str(tmp_path))
    return VocabularyStore(tmp_path)


def card(store, word="credible"):
    return next(item for item in store.listing()["words"] if item["word"] == word)


def dictionary_result(word="credible"):
    return {
        "word": word,
        "senses": [
            {
                "definition": "Believable.",
                "example": "A credible source.",
                "part_of_speech": "adjective",
                "synonyms": [],
            }
        ],
        "source": {
            "name": "Example",
            "url": "https://example.com/credible",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        },
        "pronunciation": "",
        "availability": "online dictionary",
    }


def test_words_notes_and_review_survive_restart(notebook):
    saved = notebook.save({**card(notebook), "own_words": "Something I have reasons to believe."})
    reviewed = notebook.review(
        {
            "word": "credible",
            "revision": saved["revision"],
            "rating": "good",
            "own_example": "We need credible evidence.",
        }
    )
    reopened = VocabularyStore(notebook.directory)
    restored = card(reopened)
    assert restored["own_words"] == saved["own_words"]
    assert restored["own_example"] == "We need credible evidence."
    assert restored["due"] == reviewed["due"] and restored["reviews"] == 1
    assert restored["box"] == 1
    with pytest.raises(VocabularyConflict):
        notebook.review({"word": "credible", "revision": saved["revision"], "rating": "good"})


@pytest.mark.parametrize("rating,days,box", [("hard", 1, 0), ("good", 1, 1), ("easy", 3, 2)])
def test_schedule(notebook, monkeypatch, rating, days, box):
    monkeypatch.setattr("prose.vocabulary.time.time", lambda: 1000000)
    result = notebook.review({"word": "credible", "revision": 0, "rating": rating})
    assert result["due"] == 1000000 + days * 86400
    assert result["box"] == box
    again = notebook.review({"word": "credible", "revision": result["revision"], "rating": "again"})
    assert again["due"] == 1000600 and again["lapses"] == 1 and again["box"] == 0


def test_online_result_is_cached_and_offline_never_calls_provider(notebook, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "prose.vocabulary.fetch_dictionary",
        lambda word: calls.append(word) or dictionary_result(word),
    )
    assert notebook.lookup("credible")["availability"] == "online dictionary"
    notebook.settings({"online": False})
    assert notebook.lookup("credible")["availability"] == "saved dictionary lookup"
    assert calls == ["credible"]


def test_api_outage_uses_offline_dictionary(notebook, monkeypatch):
    def unavailable(_):
        raise urllib.error.HTTPError("https://example.com", 403, "Forbidden", {}, None)

    monkeypatch.setattr("prose.vocabulary.fetch_dictionary", unavailable)
    path = notebook.directory / "wordnet.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE lexicon (word TEXT PRIMARY KEY, senses TEXT)")
    connection.execute(
        "INSERT INTO lexicon VALUES (?,?)",
        (
            "resilient",
            json.dumps(
                [
                    {
                        "definition": "Recovering after difficulty.",
                        "example": "",
                        "synonyms": [],
                        "part_of_speech": "adjective",
                    }
                ]
            ),
        ),
    )
    connection.commit()
    connection.close()
    result = notebook.lookup("resilient")
    assert result["availability"] == "offline dictionary"
    assert result["source"]["license"] == "CC BY 4.0"


def test_json_restore_preserves_progress_and_existing_edits(notebook, tmp_path):
    saved = notebook.save({**card(notebook), "own_words": "Believable with reasons."})
    notebook.review({"word": saved["word"], "revision": saved["revision"], "rating": "easy"})
    notebook.record_usage(
        "session:0", "credible evidence, not incredible luck", notebook.focus_words()
    )
    backup = notebook.export()
    restored = VocabularyStore(tmp_path / "restored")
    restored.import_backup(backup)
    assert card(restored)["due"] == card(notebook)["due"]
    assert card(restored)["own_words"] == "Believable with reasons."
    assert card(restored)["uses"] == 1
    current = restored.save({**card(restored), "own_words": "A newer note"})
    restored.import_backup(backup)
    assert card(restored)["own_words"] == current["own_words"]
    assert card(restored)["uses"] == 1


def test_import_validation_is_atomic_and_anki_retains_attribution(notebook):
    before = len(notebook.listing()["words"])
    valid = {
        "word": "resilient",
        "definition": "Able to recover.",
        "attribution": dictionary_result()["source"],
    }
    with pytest.raises(ValueError):
        notebook.import_backup(
            {"format": "prose-vocabulary", "version": 1, "words": [valid, {"word": "invalid"}]}
        )
    assert len(notebook.listing()["words"]) == before
    notebook.save(valid)
    text = notebook.anki_text()
    assert "#separator:Tab" in text and "CC BY 4.0" in text
    assert "https://example.com/credible" in text


@pytest.mark.parametrize("word", ["../secret", "https://evil", "", "word\nword", 42])
def test_lookup_words_are_bounded(word):
    with pytest.raises(ValueError):
        normalize_word(word)


def test_offline_installer_rejects_unexpected_archive(tmp_path):
    archive = tmp_path / "invalid.zip"
    archive.write_bytes(b"not the expected source")
    with pytest.raises(ValueError, match="checksum"):
        install_wordnet(archive, tmp_path / "dict")


def test_focus_words_only_go_to_coach_and_usage_is_not_recall(notebook):
    from prose.copilot import ModelSettings

    class Model:
        settings = ModelSettings("http://localhost", "test")
        calls = []

        def complete_json(self, prompt, context, **kwargs):
            self.calls.append((prompt, context))
            if prompt != COACH_PROMPT:
                assert "target_words" not in context
                return {"reply": "What evidence supports your claim?"}
            return {
                "suggestion": "Let us examine the premise.",
                "why": "Find common ground.",
                "feedback": "You used premise.",
                "vocabulary_feedback": "You used premise.",
            }

    model = Model()
    session = DebateSession(DebateConfig("Evidence", "Support claims"), model, notebook)
    opening = session.start()
    assert model.calls[0][1]["target_words"]
    assert model.calls[0][1]["user"] == {"position": "Support claims"}
    assert "persona" not in model.calls[0][1]["user"]
    assert model.calls[0][1]["opponent"]["persona"] == "maga"
    assert model.calls[0][1]["user_used_target_words"] == []
    assert opening["coach"]["feedback"] == ""
    assert opening["coach"]["vocabulary_feedback"].startswith("Suggested word")
    result = session.reply("We need credible evidence.", 0)
    assert model.calls[-1][1]["user_used_target_words"] == ["credible"]
    assert result["words_used"] == ["credible"]
    assert card(notebook)["uses"] == 1 and card(notebook)["reviews"] == 0


def test_boolean_revision_cannot_overwrite_notes(notebook):
    with pytest.raises(VocabularyConflict):
        notebook.save({**card(notebook), "revision": False})
    with pytest.raises(VocabularyConflict):
        notebook.review({"word": "credible", "revision": False, "rating": "easy"})


def test_collection_migration_is_idempotent_and_preserves_edited_words(notebook):
    saved = notebook.save({**card(notebook), 'own_words': 'My important note'})
    reviewed = notebook.review({'word': 'credible', 'revision': saved['revision'],
                                'rating': 'easy'})
    with notebook.connection() as connection:
        connection.execute("DELETE FROM settings WHERE key='collections-v1'")
        connection.execute("DELETE FROM words WHERE word='affidavit'")
    reopened = VocabularyStore(notebook.directory)
    assert card(reopened)['own_words'] == 'My important note'
    assert card(reopened)['due'] == reviewed['due']
    assert 'under oath' in card(reopened, 'affidavit')['definition']
    count = len(reopened.listing()['words'])
    assert len(VocabularyStore(notebook.directory).listing()['words']) == count
    legal = card(reopened, 'lien')
    assert 'property' in legal['definition'] and 'organ' not in legal['definition']
    assert legal['source_url'] == 'https://www.uscourts.gov/glossary'


def test_new_collection_card_progress_survives_backup_restore(notebook, tmp_path):
    current = card(notebook, 'affidavit')
    notebook.review({'word': current['word'], 'revision': current['revision'], 'rating': 'good'})
    restored = VocabularyStore(tmp_path / 'restored-collections')
    restored.import_backup(notebook.export())
    assert card(restored, 'affidavit')['reviews'] == 1
    assert card(restored, 'affidavit')['attribution']['name'].startswith('Administrative Office')


def test_offline_browse_paginates_and_escapes_search(notebook):
    with sqlite3.connect(notebook.directory / 'wordnet.sqlite3') as connection:
        connection.execute('CREATE TABLE lexicon (word TEXT PRIMARY KEY, senses TEXT)')
        connection.executemany('INSERT INTO lexicon VALUES (?, ?)',
                               [(f'word{i:03}', json.dumps([{'definition': 'Meaning'}]))
                                for i in range(65)])
    first = notebook.library({})
    assert first['total'] == first['matched'] == 65 and len(first['words']) == 30
    assert first['has_more']
    last = notebook.library({'offset': 60})
    assert len(last['words']) == 5 and not last['has_more']
    assert notebook.library({'query': '%'})['matched'] == 0
    assert notebook.library({'query': 'word00'})['matched'] == 10
    for bad in (True, -1, 200001, '30'):
        with pytest.raises(ValueError):
            notebook.library({'offset': bad})


def test_missing_dictionary_does_not_hide_bundled_collections(notebook):
    assert notebook.library({})['installed'] is False
    listing = notebook.listing()
    assert len(listing['words']) > 600
    assert sum(listing['category_counts'].values()) == len(listing['words'])


def test_vocab_http_roundtrip_and_origin_rejection(notebook):
    site = build_site("127.0.0.1", 0)
    worker = threading.Thread(target=site.server.serve_forever, daemon=True)
    worker.start()

    def post(action, data, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            site.url + "/api/vocabulary/" + action, data=json.dumps(data).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    try:
        result = post("list", {})
        assert len(result["words"]) > 600
        assert len(result['categories']) >= 8
        post("settings", {"online": False})
        assert post("lookup", {"word": "credible"})["availability"] == "saved word notebook"
        with urllib.request.urlopen(site.url + "/api/vocabulary/export") as response:
            assert response.headers.get("Access-Control-Allow-Origin") is None
            assert json.load(response)["format"] == "prose-vocabulary"
        with pytest.raises(urllib.error.HTTPError) as rejected:
            post("settings", {"online": True}, "https://example.com")
        assert rejected.value.code == 403
    finally:
        site.server.shutdown()
        site.server.server_close()
        worker.join(3)
