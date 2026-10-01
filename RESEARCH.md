# Scouting research library

Open **Research** at `http://127.0.0.1:8005/research` to browse categories, search
saved full text, inspect extracted documents and open original publications.
Browsing and search work offline. Choose **Scout removal** in Debate practice,
or open `/practice?topic=scouting`, to use the library in an Indiana guideline
discussion. Both AI roles receive up to eight relevant passages each turn.
The coach displays the passages actually supplied, dates, page numbers and URLs.

## Coverage — October 1, 2026

The initial installation has **229 saved sources, 3,794 passages and 12 categories**:

- October 2025 Rules and Regulations and Charter and Bylaws; membership standards,
  applications and 2026 charter templates.
- All Guide to Safe Scouting chapters linked from its table of contents, including
  youth protection, discipline, camping, aquatics, transportation and reporting.
- Safeguarding Youth, Barriers to Abuse FAQs, bullying prevention and incident guides.
- Guide to Advancement 2025, 2026 updates, board reviews and supporting forms.
- Complete 2026 Inclusion Toolbox, disability resources, awards/insignia guides.
- Registration and renewal guides (including September 2026 updates), troop
  leadership resources, program values and linked forms.
- Separately labeled federal legal context: the corporate charter, historical
  *Dale* opinion and ADA exemptions. Indiana corporate-member definition and
  termination statutes are **2025 mirror snapshots**, not verified 2026 law.

Counts represent source records; some publications have multiple publisher URLs.
Retrieval suppresses identical copies. Complete extracted text is stored, rather
than short summaries. PDF page numbers count from the start of the file and may
differ from printed page numbers. Extraction can lose layout, tables and images.
Local OCR is available for images and PDF pages without embedded text; OCR can
misread names and numbers, so check the original before relying on a passage.

Two inventory entries remain unavailable: the current internal Registration
Guidebook (requires Scouting registrar access), and readable text from the current
official Indiana Code website. The revocation rule also references **Procedures
for Maintaining Standards of Membership and Leadership**; that full publication
has not been obtained. A camp-training appendix is not the complete procedure.

This collection covers public national guides, not every publication ever issued.
It excludes commercial handbooks, restricted manuals, every merit-badge pamphlet,
and unsupplied local council/unit policies. Older documents still linked by the
publisher remain visible. Check editions, signed agreements and actual authority.
Advancement appeals, youth leadership removal, unit exclusion and national
membership revocation are distinct processes. A cited passage does not guarantee
that the AI interpreted it correctly.

## Import the situation folder from Google Drive

1. Download the Drive folder as a ZIP.
2. Put it in `C:\repos\ProSe\.prose\scouting-case`.
3. Open Research → **Import your situation documents** → **Import case folder**.
4. Inspect the import report for incomplete or skipped files.
5. In Debate practice, select the Scouting library and enable **Include my imported
   case documents** when you want those passages used.

Supports PDF, DOCX body text, PPTX slide text, XLSX cell values, text/Markdown,
CSV, JSON, EML email bodies, and local OCR for images and scanned PDF pages. ZIP
entries are read without extracting paths. Nested ZIPs and unsupported formats
are reported; email attachments must be saved separately. Limits: 30 MB per
expanded file, 500 MB per import, 2,000 files, 40 megapixels per image and 1,000
pages per PDF.
Repeat imports update source records without duplicating search entries. Renamed
files/archives are separate records. Deleting an original does not remove its index.

Import and search run locally. Enabling case documents in debate sends relevant
excerpts to the selected AI provider, and possibly Saul if consultation is enabled.
This option starts off. Correspondence and allegations are labeled as case material,
not established facts or national policy. Select the intended provider before using
private records.

## Rebuild and storage

```powershell
python -m pip install -e ".[research,ocr]"
python scripts/ingest_scouting.py
# Download fresh originals instead of reusing the cache:
python scripts/ingest_scouting.py --refresh
```

`prose/data/scouting_sources.json` lists the seeds. Discovery follows only listed
guide prefixes and linked PDFs on allowed hosts. Redirects are checked; downloads
are capped at 50 MB per source and discovery at 600 URLs. Restricted pages remain
unavailable. Source text is reference data, never an instruction to the application.

The two public-domain Indiana statutory snapshots are identified in
`prose/data/scouting_statutory_snapshots.json`. The browser reader could read the
2025 mirror when direct downloads failed. Refreshing does not change the original
capture date or make the snapshots verified current law.

OCR runs locally with RapidOCR and ONNX Runtime; first-time setup installs the
open-source OCR package and bundled recognition models. The OCR models are not
fine-tuned by this ingestion.

Files under `PROSE_DATA_DIR` (default `.prose/`, ignored by Git):

- `research.sqlite3`: metadata, extracted full text and SQLite FTS5 index.
- `scouting/originals/`: downloaded originals, hashes and acquisition metadata.
- `scouting/coverage.json`: last national-import inventory and extraction gaps.
- `scouting-case/`: user-provided files and ZIPs.

Each document update is atomic. Failed refreshes retain the prior good text with
a warning. The Research page reflects later case imports too. Back up `.prose`
to preserve the local library. The models are not fine-tuned by this ingestion.

## Verification

Tests cover persistence, full-text search, source provenance, deduplication,
failed-refresh preservation, case/legal filters, governing-rule prioritization,
ZIP paths, DOCX/email extraction, debate source delivery, citation-ID validation,
HTTP routes and cross-origin rejection. JavaScript has also been syntax checked.

Live Qwen smoke runs are in `artifacts/scouting-debate-live*.json`. The first run
correctly distinguished advancement appeals from membership removal, but
overinterpreted a charter clause and mishandled feedback chronology. Instructions
and scope notes were adjusted before a rerun. The rerun still misread the express
discretion clause and gave inaccurate chronology feedback. Retrieval delivered the
correct text, but the model's interpretation remains unreliable. These checks do
not establish legal accuracy or courtroom readiness. Browser visual verification
was unavailable.
