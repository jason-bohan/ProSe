from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from prose.case_import import case_text, import_case_folder
from prose.copilot import CopilotError, ModelSettings
from prose.debate import OPPONENT_PROMPT, DebateConfig, DebateSession
from prose.research import ResearchStore, chunks, source_id
from prose.web import build_site


def add(store, title="Rules", text="Membership revocation and constructive discipline.",
        url="https://www.scouting.org/rules/", kind="policy", **metadata):
    meta = {"title": title, "url": url, "category": "National rules", "kind": kind,
            "status": "ready", "sha256": title, "fetched_at": "2026-10-01", **metadata}
    store.ingest(meta, [("Section 1", text)])
    return source_id(url)


def test_persistent_full_text_and_provenance(tmp_path):
    store = ResearchStore(tmp_path)
    sid = add(store, text="Opening. " * 1000 + "Unusual final membership clause.")
    store = ResearchStore(tmp_path)
    result = store.search("unusual final")["results"][0]
    assert result["source_id"] == sid and result["locator"] == "Section 1"
    assert "Unusual final membership clause" in result["text"]
    assert len(store.document(sid)["passages"]) > 3
    assert store.catalog()["ready"] == 1


def test_chunking_keeps_start_end_and_bounds():
    text = "opening " + "word " * 1500 + "lastsentence"
    parts = chunks(text)
    assert parts[0].startswith("opening") and parts[-1].endswith("lastsentence")
    assert all(len(p) <= 2200 for p in parts)
    assert chunks("") == []


def test_reimport_replaces_without_duplicate_fts_and_failure_keeps_good_copy(tmp_path):
    store = ResearchStore(tmp_path)
    sid = add(store, text="obsolete phrase")
    add(store, text="current phrase")
    assert store.search("obsolete")["total"] == 0
    assert store.search("current")["total"] == 1
    store.ingest({"url": "https://www.scouting.org/rules/", "status": "unavailable",
                  "error": "HTTP 503", "fetched_at": "2026-10-02"}, [])
    assert store.document(sid)["source"]["refresh_error"] == "HTTP 503"
    assert store.search("current")["total"] == 1


def test_search_filters_and_treats_fts_syntax_as_text(tmp_path):
    store = ResearchStore(tmp_path)
    add(store)
    add(store, "Statute", "Membership termination.", "https://example.com/law", "law")
    add(store, "Email", "Membership notice.", "case://email", "case",
        category="Your case documents")
    assert len(store.retrieve("membership")) == 1
    assert len(store.retrieve("membership", include_law=True)) == 2
    assert len(store.retrieve("membership", include_case=True)) == 2
    # NOT is searched as the literal prefix of "notice", not treated as an operator.
    assert store.search('" OR * NEAR( NOT: --')['total'] == 1
    assert store.search("membership", "Your case documents")["total"] == 1
    assert store.search("membership", offset=1, limit=1)["has_more"]
    with pytest.raises(ValueError):
        store.search("x", offset=-1)
    with pytest.raises(ValueError):
        store.search(None)


def test_removal_retrieval_prioritizes_governing_rule_over_advancement_form(tmp_path):
    store = ResearchStore(tmp_path)
    url = ("https://www.scouting.org/wp-content/uploads/2025/11/"
           "2025-Rules_Regulations_NEB-Approved-10.28.2025.pdf")
    add(store, "National rules", "Denial and revocation of registration. "
        "See Procedures for Maintaining Standards of Membership and Leadership.", url)
    add(store, "Advancement appeal", "review process appeal decision " * 20,
        "https://example.com/advancement")
    result = store.retrieve("What review process applies when removing a Scout?")
    assert result[0]["title"] == "National rules"


def test_duplicate_publication_does_not_fill_context(tmp_path):
    store = ResearchStore(tmp_path)
    add(store, sha256="same")
    add(store, url="https://example.com/duplicate", sha256="same")
    assert len(store.retrieve("membership")) == 1


def test_import_zip_without_extracting_paths_and_repeat_is_idempotent(tmp_path):
    store = ResearchStore(tmp_path)
    folder = tmp_path / "scouting-case"
    folder.mkdir()
    with zipfile.ZipFile(folder / "drive.zip", "w") as z:
        z.writestr("letters/notice.txt", "An allegation in a membership notice.")
        z.writestr("../../escape.txt", "should never escape")
        z.writestr("/absolute.txt", "should never escape")
        z.writestr("image.png", b"not text")
    result = import_case_folder(store)
    assert result["ready"] == 1 and result["incomplete"] == 3
    assert not (tmp_path / "escape.txt").exists()
    assert not (folder / "letters").exists()
    import_case_folder(store)
    assert store.catalog()["case_ready"] == 1
    assert not store.catalog()["installed"]
    assert not store.retrieve("allegation")
    assert store.retrieve("allegation", include_case=True)[0]["kind"] == "case"


def test_docx_and_email_extract_body_with_limits_not_fake_policy():
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                   'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Meeting notice</w:t>'
                   '</w:r></w:p></w:body></w:document>')
    parts, warnings = case_text("notice.docx", blob.getvalue())
    assert parts[0][1] == "Meeting notice" and warnings
    parts, _ = case_text("message.eml",
                         b"From: parent@example.test\nSubject: Review\n\nMy account.")
    assert "Subject: Review" in parts[0][1] and "My account." in parts[0][1]


def test_presentation_and_spreadsheet_text_is_indexable_without_office_install():
    slides = io.BytesIO()
    with zipfile.ZipFile(slides, "w") as deck:
        deck.writestr("ppt/slides/slide2.xml", '<p:sld xmlns:p="x" '
                      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                      '<a:p><a:r><a:t>Removal process</a:t></a:r></a:p></p:sld>')
        deck.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="x" '
                      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                      '<a:p><a:r><a:t>Scouting rules</a:t></a:r></a:p></p:sld>')
    parts, warnings = case_text("rules.pptx", slides.getvalue())
    assert parts == [("Slide 1", "Scouting rules"), ("Slide 2", "Removal process")]
    assert warnings

    workbook = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(workbook, "w") as book:
        book.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}">'
                      '<sheets><sheet name="Timeline" sheetId="1" r:id="rId1"/>'
                      '</sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{package}">'
                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                      'Type="worksheet"/></Relationships>')
        book.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"><si>'
                      '<t>Hearing notice</t></si></sst>')
        book.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>'
                      '<row r="1"><c r="A1" t="s"><v>0</v></c>'
                      '<c r="B1"><v>15</v></c></row></sheetData></worksheet>')
    parts, warnings = case_text("timeline.xlsx", workbook.getvalue())
    assert "Hearing notice" in parts[0][1] and "B1=15" in parts[0][1]
    assert warnings


class ResearchModel:
    settings = ModelSettings("http://localhost:1234/v1", "test")

    def __init__(self, invalid=False):
        self.calls, self.invalid = [], invalid

    def complete_json(self, prompt, context, **kwargs):
        self.calls.append(context)
        if prompt == OPPONENT_PROMPT:
            return {"reply": "Which written policy applies?"}
        sid = "S-deadbeef-99" if self.invalid else context["sources"][0]["id"]
        return {"suggestion": "Please identify the applicable procedure.",
                "why": f"The supplied passage identifies the issue. [{sid}]"}


def test_debate_passes_sources_to_both_roles_with_provenance(tmp_path):
    store = ResearchStore(tmp_path)
    add(store)
    model = ResearchModel()
    session = DebateSession(DebateConfig("Membership removal", "Constructive discipline",
                                        knowledge_pack="scouting"), model, research=store)
    result = session.start()
    assert result["coach"]["research_sources"][0]["cited"]
    session.reply("What about constructive discipline?", 0)
    assert all(c["sources"] for c in model.calls)
    assert all("adult-leader" in c["research_scope"] for c in model.calls)


def test_unknown_citation_fails_and_missing_pack_is_explicit(tmp_path):
    store = ResearchStore(tmp_path)
    config = DebateConfig("Membership", "review", knowledge_pack="scouting")
    with pytest.raises(ValueError, match="Install"):
        DebateSession(config, ResearchModel(), research=store)
    add(store)
    with pytest.raises(CopilotError, match="cited a passage"):
        DebateSession(config, ResearchModel(invalid=True), research=store).start()
    with pytest.raises(ValueError):
        DebateConfig.from_dict({"topic": "x", "position": "y", "knowledge_pack": "unknown"})


def test_research_http_page_search_and_origin_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("PROSE_DATA_DIR", str(tmp_path))
    site = build_site("127.0.0.1", 0)
    thread = threading.Thread(target=site.server.serve_forever, daemon=True)
    thread.start()
    try:
        add(site.app.research)
        with urllib.request.urlopen(site.url + "/research") as r:
            page = r.read().decode()
            assert 'lang="en"' in page and "Import case folder" in page
        request = urllib.request.Request(site.url + "/api/research/search",
                                         data=b'{"query":"revocation"}',
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as r:
            assert json.load(r)["total"] == 1
        request.add_header("Origin", "https://untrusted.example")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(request)
        assert e.value.code == 403
    finally:
        site.server.shutdown()
        site.server.server_close()
        thread.join(timeout=5)


def test_html_extraction_uses_document_content_and_rejects_empty_shell():
    pytest.importorskip("bs4")
    pytest.importorskip("pypdf")
    from scripts.ingest_scouting import html_content

    body = ("<html><body><nav>irrelevant menus</nav>"
            '<div class="elementor-widget-theme-post-content"><h2>Conduct</h2><p>'
            + "Constructive discipline and applicable youth protection requirements. " * 4
            + "</p></div></body></html>")
    _, sections, _ = html_content(body.encode())
    assert sections[0][0] == "Conduct"
    assert "irrelevant" not in sections[0][1]
    with pytest.raises(ValueError, match="No readable"):
        html_content(b"<body>You need to enable JavaScript to run this app.</body>")


@pytest.mark.parametrize("url", ["http://www.scouting.org/test", "https://127.0.0.1/data",
                                  "https://www.scouting.org.evil.test/a.pdf",
                                  "https://www.scouting.org:8443/a.pdf"])
def test_importer_disallows_unlisted_hosts_and_unexpected_ports(url):
    pytest.importorskip("bs4")
    pytest.importorskip("pypdf")
    from scripts.ingest_scouting import normalized

    with pytest.raises(ValueError):
        normalized(url)
