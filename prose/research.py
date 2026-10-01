"""Persistent, offline full-text research packs with document/page provenance."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from .lexicon import data_directory

PACK = "scouting"
PACK_TITLE = "Scouting America · national guides and Indiana context"
PACK_SCOPE = (
    "Public national policy guides and linked reference documents. Local troop rules, "
    "council bylaws, the signed charter agreement and restricted membership procedures "
    "must be obtained separately. Ingestion is not a determination that a rule applies."
)
SCOUTING_CONTEXT = (
    "This is a Scouting America guideline discussion in Indiana. Distinguish a youth's "
    "removal from a troop, removal from a leadership position, temporary activity exclusion, "
    "roster/renewal administration, and national membership revocation. Do not transfer "
    "a duty to register members or select adult leaders into authority to expel youth. "
    "adult-leader rules to youth. Internal policies are not statutes. Advancement appeals "
    "are not automatically membership appeals. Establish the decision maker, written reason, "
    "applicable policy edition and review route. Do not invent a right to notice or a hearing. "
    "Indiana nonprofit law depends on the entity and statutory membership definition; "
    "Scouting registration alone does not establish either. Older guidance may be superseded. "
    "If excerpts conflict or omit a procedure, identify the gap and request the actual rule."
)


def source_id(url: str) -> str:
    return "S-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def chunks(text: str, maximum: int = 2200) -> list[str]:
    """Preserve every character, with overlap at paragraph/sentence boundaries."""
    text = text.replace("\x00", "").strip()
    result = []
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + maximum // 2, end),
                           text.rfind(". ", start + maximum // 2, end))
            if boundary >= 0:
                end = boundary + 1
        result.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(start + 1, end - 180)
    return result


def _terms(query: str, *, expand: bool = False) -> str:
    words = re.findall(r"[a-zA-Z0-9]{2,40}", query.lower())
    stop = {"a", "an", "the", "and", "or", "in", "on", "at", "of", "to", "for", "with",
            "that", "this", "is", "are", "was", "be", "by", "as", "i", "we", "our", "my",
            "you", "your", "it", "what", "which", "how", "who", "can", "should", "would",
            "could", "want", "scout", "scouts", "scouting", "america", "bsa", "boy", "troop",
            "debate", "discuss", "discussion", "please", "know", "guideline", "guidelines",
            "policy", "policies", "question", "about"}
    words = [w for w in dict.fromkeys(words) if w not in stop][:24]
    if expand and any(w.startswith(("remov", "expel", "kick", "dismiss", "revo", "suspen"))
                      for w in words):
        words += ["membership", "revocation", "denial", "discipline", "appeal", "termination"]
    return " OR ".join('"' + word + '"*' for word in dict.fromkeys(words))


class ResearchStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or data_directory()).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "research.sqlite3"
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, pack TEXT NOT NULL, title TEXT NOT NULL,
                    category TEXT NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL,
                    status TEXT NOT NULL, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS passages (
                    id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, locator TEXT NOT NULL,
                    citation_id TEXT NOT NULL UNIQUE, text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS passages_source ON passages(source_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                    title, text, tokenize='porter unicode61');
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def ingest(self, meta: dict, sections: list[tuple[str, str]]) -> None:
        """Replace one source atomically; a failed refresh preserves its last good text."""
        sid = source_id(meta["url"])
        meta = {**meta, "id": sid}
        rows = [(locator, part) for locator, text in sections for part in chunks(text)]
        meta["passages"] = len(rows)
        meta["characters"] = sum(len(text) for _, text in sections)
        with closing(self.connect()) as db, db:
            old = db.execute("SELECT metadata FROM sources WHERE id=?", (sid,)).fetchone()
            if old and meta["status"] != "ready":
                previous = json.loads(old["metadata"])
                if previous.get("characters", 0):
                    meta = {**previous, "refresh_error": meta.get("error", "Refresh failed"),
                            "last_attempt": meta.get("fetched_at")}
                    db.execute("UPDATE sources SET metadata=? WHERE id=?",
                               (json.dumps(meta), sid))
                    return
            db.execute("DELETE FROM search WHERE rowid IN "
                       "(SELECT id FROM passages WHERE source_id=?)", (sid,))
            db.execute("DELETE FROM passages WHERE source_id=?", (sid,))
            db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?)",
                       (sid, meta.get("pack", PACK), meta["title"], meta["category"],
                        meta.get("kind", "policy"),
                        meta["url"], meta["status"], json.dumps(meta)))
            for number, (locator, part) in enumerate(rows, 1):
                cur = db.execute("INSERT INTO passages(source_id,locator,citation_id,text) "
                                 "VALUES (?,?,?,?)", (sid, locator, f"{sid}-{number}", part))
                db.execute("INSERT INTO search(rowid,title,text) VALUES (?,?,?)",
                           (cur.lastrowid, meta["title"] + " " + locator, part))

    def catalog(self) -> dict:
        with closing(self.connect()) as db:
            sources = [json.loads(r[0]) for r in db.execute(
                "SELECT metadata FROM sources ORDER BY category,title")]
        return {"id": PACK, "title": PACK_TITLE, "scope": PACK_SCOPE,
                "installed": any(s["status"] == "ready" and s.get("kind") != "case"
                                 for s in sources),
                "case_ready": sum(s["status"] == "ready" and s.get("kind") == "case"
                                  for s in sources),
                "national_ready": sum(s["status"] == "ready" and s.get("kind") != "case"
                                       for s in sources),
                "ready": sum(s["status"] == "ready" for s in sources),
                "unavailable": sum(s["status"] != "ready" for s in sources),
                "passages": sum(s.get("passages", 0) for s in sources),
                "categories": dict(Counter(s["category"] for s in sources)), "sources": sources}

    def search(self, query: str, category: str = "", *, offset: int = 0,
               limit: int = 20, include_law: bool = True, include_case: bool = True,
               expand: bool = False, only_source: str = "") -> dict:
        if not isinstance(query, str) or len(query) > 4000:
            raise ValueError("Search must be text of at most 4,000 characters")
        if not isinstance(category, str) or len(category) > 100:
            raise ValueError("Invalid category")
        if type(offset) is not int or not 0 <= offset <= 100_000:
            raise ValueError("Invalid search offset")
        limit = max(1, min(100, limit))
        expression = _terms(query, expand=expand)
        if not expression:
            return {"results": [], "total": 0, "offset": offset, "has_more": False}
        filters = "search MATCH ? AND s.status='ready'"
        args: list = [expression]
        if category:
            filters += " AND s.category=?"
            args.append(category)
        if only_source:
            filters += " AND s.id=?"
            args.append(only_source)
        if not include_law:
            filters += " AND s.kind != 'law'"
        if not include_case:
            filters += " AND s.kind != 'case'"
        base = (" FROM search JOIN passages p ON p.id=search.rowid "
                "JOIN sources s ON s.id=p.source_id WHERE " + filters)
        with closing(self.connect()) as db:
            total = db.execute("SELECT count(*)" + base, args).fetchone()[0]
            rows = db.execute("SELECT p.*,s.metadata,bm25(search,2,1) AS rank" + base
                              + " ORDER BY CASE WHEN instr(lower(substr(p.text,1,200)),"
                              "'contents')>0 THEN 1 ELSE 0 END,rank,p.id LIMIT ? OFFSET ?",
                              (*args, limit, offset)).fetchall()
        results = []
        for row in rows:
            meta = json.loads(row["metadata"])
            results.append({"id": row["citation_id"], "source_id": row["source_id"],
                            "title": meta["title"], "url": meta["url"],
                            "locator": row["locator"], "text": row["text"],
                            "category": meta["category"], "kind": meta.get("kind", "policy"),
                            "fetched_at": meta.get("fetched_at", ""),
                            "edition": meta.get("edition", "Edition not stated"),
                            "scope_note": meta.get("scope_note", ""),
                            "sha256": meta.get("sha256", "")})
        return {"results": results, "total": total, "offset": offset,
                "has_more": offset + limit < total}

    def document(self, sid: str) -> dict:
        if not isinstance(sid, str):
            raise ValueError("source_id must be text")
        with closing(self.connect()) as db:
            row = db.execute("SELECT metadata FROM sources WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise KeyError("Research source not found")
            passages = [dict(r) for r in db.execute(
                "SELECT citation_id,locator,text FROM passages WHERE source_id=? ORDER BY id",
                (sid,))]
        return {"source": json.loads(row[0]), "passages": passages}

    def retrieve(self, query: str, *, include_law: bool = False,
                 include_case: bool = False) -> list[dict]:
        anchors = []
        if re.search(r"\b(remov\w*|expel\w*|kick\w*|dismiss\w*|revok\w*|suspend\w*)\b",
                     query, re.I):
            # Retrieve governing membership/conduct passages before generic "review" hits,
            # which otherwise overwhelmingly retrieve advancement appeals and forms.
            routes = [
                ("https://www.scouting.org/wp-content/uploads/2025/11/"
                 "2025-Rules_Regulations_NEB-Approved-10.28.2025.pdf", "revocation registration"),
                ("https://www.scouting.org/health-and-safety/gss/gss01/",
                 "constructive discipline"),
                ("https://www.scouting.org/health-and-safety/gss/gss01/", "revocation"),
                ("https://www.scouting.org/wp-content/uploads/2026/04/"
                 "524-95626-Annual-Charter-Agreement.pdf", "management leadership committee"),
            ]
            for url, terms in routes:
                hits = self.search(terms, only_source=source_id(url), limit=10)["results"]
                anchors += [s for s in hits if not self._contents_page(s["text"])][:1]
        if include_case:
            anchors += self.search(query[:4000], "Your case documents", limit=2)["results"]
        candidates = self.search(query[:4000], limit=100, include_law=include_law,
                                 include_case=include_case, expand=True)["results"]
        selected, counts, seen = [], Counter(), set()
        for item in anchors + candidates:
            key = (item["sha256"], item["locator"], item["text"])
            if key in seen or self._contents_page(item["text"]):
                continue
            # Identical publications at different URLs share the per-document limit.
            document_key = item["sha256"] or item["source_id"]
            if counts[document_key] >= 2:
                continue
            counts[document_key] += 1
            seen.add(key)
            selected.append(item)
            if len(selected) == 8:
                break
        return selected

    @staticmethod
    def _contents_page(text: str) -> bool:
        return bool(re.search(r"\bCONTENTS\b", text[:200], re.I))
