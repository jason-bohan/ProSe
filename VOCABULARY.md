# Vocabulary and debate learning

## Use it

1. Open `/vocabulary`. Study a due card before revealing its definition.
   The notebook now includes 625 distinct cards after combining the original
   starter set with 617 sourced collection entries. Browse eight category buttons,
   filter by difficulty, or search definitions. Filters also scope recall practice.
2. Explain the meaning in your own words and write a sentence. Reveal, compare,
   then rate Again, Hard, Good, or Easy. Your notes and next review date are saved.
3. Use dictionary lookup to choose a specific sense. Copy it into the editor,
   add root/family notes or a reading/listening source, and click **Save word**.
4. Mark words for debate practice. A new debate uses the first three focus words
   ordered by due date and word. The coach panel displays the actual selection.
5. In `/practice`, choose listening, argument structure, or free debate. The
   coach suggests natural usage and comments on your wording. Exact whole-word
   matches in your replies count as uses; they are not evidence of correct usage
   or long-term retention. The model's feedback is separate from recall grading.

## Your reference list, translated into exercises

| Reference or approach | Exercise in this app |
| --- | --- |
| Norman Lewis, Word Power Made Easy | Root notes and related word families |
| Chris Lele, The Vocabulary Builder Workbook | Themes, levels, examples and recall checks |
| Merriam-Webster’s Vocabulary Builder | Roots, prefixes/suffixes and family comparison |
| Anki | Active recall, spaced reviews and Anki text export |
| Vocabulary.com | Choose a dictionary sense and practice it in context |
| Magoosh | Essential, Intermediate and Advanced word levels |
| A Way with Words / linguistic podcasts | Reading/listening source and personal word log |
| Nonfiction audiobooks / Audible / Libby | Capture a word, source, and your own contextual sentence |
| Publications and wide reading | Save new words with where you encountered them |
| Explain-it-simply notebook practice | Own-words explanation before revealing a definition |
| Bo Seo | Listening summary, a precise topic map, and RISA-informed coaching |

These are independent exercises. No commercial books, decks, articles, audiobook
recordings, or podcast transcripts are bundled. Original starter definitions and
example sentences were written for ProSe. Related families sometimes contrast
nearby terms; they do not imply the words are interchangeable.

## Themed collections and full dictionary browsing

The expanded study collection groups words into Debate & reasoning, Evidence &
research, Law & procedure, Communication & listening, Policy & ethics, Negotiation
& conflict, Precise wording, and Advanced expression. Difficulty labels are ProSe
study suggestions, not standardized reading-level scores. Source definitions and
available examples come from Open English WordNet; roots and original contextual
examples are not automatically invented for imported cards.

The Law & procedure collection uses the [U.S. Courts glossary](https://www.uscourts.gov/glossary),
retrieved October 1, 2026. These are federal-court study definitions, not a substitute
for governing law. Attribution identifies the Administrative Office of the U.S.
Courts and the public-domain status of U.S. federal government work. Entries whose
names fall outside the notebook's word validation (such as numbered chapter names)
are listed in the collection file's `court_terms_skipped` field. HTML whitespace is
normalized; no full commercial reference book is bundled.

Existing notebooks receive only missing collection words on the first upgrade.
User edits, focus selections, notes, and recall progress are preserved. The
5,000-card notebook cap still applies. Collection cards and their progress are
included in JSON backups and attributed Anki exports.

**Explore the full offline dictionary** exposes the installed 127,311-entry
dictionary with prefix search and 30-word pages. Pick a word and a specific sense,
then save it to the notebook. The categorized notebook has 40-word pages; the
general dictionary is not presented as 127,311 curated study cards.

`prose/data/vocabulary_collection_words.json` contains the editorial word selection.
`prose/data/vocabulary_collections.json` contains the distributable, attributed
cards and source hashes. With the pinned WordNet dictionary installed and a saved
copy of the federal glossary HTML, rebuild using:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts/build_vocabulary_collections.py --court-html artifacts/uscourts-glossary.html
```

Root pointers were checked against Wiktionary entries for
[credible](https://en.wiktionary.org/wiki/credible),
[equivocal](https://en.wiktionary.org/wiki/equivocal),
[infer](https://en.wiktionary.org/wiki/infer), and
[explicit](https://en.wiktionary.org/wiki/explicit). Consult a historical dictionary
for full derivations; the notebook uses brief learning pointers.

## Bo Seo and argument structure

Bo Seo describes RISA as checking whether a disagreement is **real, important,
specific, and aligned** in purpose. Our listening coach uses these ideas to
clarify the disagreement and address the opponent's strongest actual point.
It is an independent learning aid, not an official Bo Seo product.

- [Bo Seo explaining RISA](https://bigthink.com/series/the-big-think-interview/debate-framework/)
- [Harvard Law interview on Good Arguments and listening](https://hls.harvard.edu/today/up-for-debate/)

The additional **State → Support → Explain → Conclude** exercise is a general
argument scaffold. It is not presented as Seo's named four-step refutation method.
The factual/moral/policy topic map is a practical classification in this app.
Generated support must use known facts or identify missing evidence.

## Dictionary sources and attribution

### Online

[FreeDictionaryAPI.com](https://freedictionaryapi.com/) provides Wiktionary data
without an API key. The implementation follows its
[OpenAPI contract](https://freedictionaryapi.com/api/v1/openapi.json).
The provider documents a 1,000-request/hour/IP limit. ProSe sends only the lookup
word, uses a four-second timeout, caps response size, and caches normalized senses
for 30 days before trying an online refresh. An unavailable refresh can still use
the saved entry. No browser credentials, notes, case material, or debate transcript
are sent to this dictionary service.

Content is attributed to Wiktionary via FreeDictionaryAPI.com under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Original-page links,
license links, and notices remain attached to saved entries and exports.
Both a live online lookup and the installed offline dictionary were checked in
this development environment. Provider outages fall back to cached or local data.

### Offline

[Open English WordNet 2025](https://en-word.net/downloads), by the Open English
WordNet Community and derived from Princeton WordNet, is distributed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
ProSe reformats up to eight senses per lemma with definitions, selected examples,
parts of speech, and synonyms. The local import contains 127,311 distinct lemmas.
It does not supply comprehensive etymologies or recorded pronunciation audio.

The installer downloads the pinned 2025 JSON archive, verifies its SHA-256,
and builds `.prose/wordnet.sqlite3` before replacing the previous dictionary.
The archive and attribution record are retained. Install once while online:

```sh
python -m prose.lexicon
# Or use a previously downloaded archive:
python -m prose.lexicon --archive path/to/english-wordnet-2025-json.zip
```

SHA-256 of the checked release:
`7d749f6e2c39e6970e4997839dcf6e42fd281f3c2fae0171d2192bae8cfa4b51`.
This pin was recorded from the downloaded official release, not a separately
signed checksum. A changed upstream file is rejected rather than silently used.

Saved cards and recall work without internet while the local ProSe server is
running. This is not a phone PWA that runs with the server switched off. Speech
playback uses the browser's installed voices and may depend on browser/platform
services. Hosted debate models need a network; local model configuration is in SETUP.md.

## Storage and backups

- Default personal database: `.prose/vocabulary.sqlite3`, ignored by Git.
- Override its directory with `PROSE_DATA_DIR` before starting the server.
- Saves and reviews use transactions. Revision checks prevent stale edits and
  duplicate ratings from overwriting newer progress. Sessions capture focus words
  when they start; change the notebook and start another debate to refresh them.
- JSON format: `format: "prose-vocabulary"`, `version: 1`, `words`, `online`, `usages`.
  Word records include definitions, source/license, personal notes, recall box,
  due timestamp, review/lapse counts, and revision. Due dates are UTC Unix seconds.
- Import validates all records before writing. New words and pristine starter
  cards are restored; already edited cards are kept. Import is a merge, not a
  destructive replacement. Current online preference is kept. Usage event IDs
  deduplicate repeated imports. Import size limit is 16 MB.
- The dictionary installation and cache are separate from notebook JSON backups.
  Retain the `.prose` directory for a full local backup while the server is stopped.
- Anki export follows the official [text import format](https://docs.ankiweb.net/importing/text-files.html).
  It includes word/definition/examples/notes and attribution, but does not transfer
  recall scheduling or review history. Import it as Basic cards in Anki.

The scheduler uses Leitner-style intervals of 1, 3, 7, 14, 30, 60 and 120 days.
Again resets a word to a ten-minute retry; Hard returns tomorrow and lowers the
box; Good advances one box; Easy advances two. This is a simple deterministic
schedule, not Anki's FSRS or a personalized memory prediction.
