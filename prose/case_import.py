"""Import user-supplied case files from a fixed private folder, without extracting ZIPs."""

from __future__ import annotations

import hashlib
import io
import re
import threading
import zipfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from xml.etree import ElementTree

from .research import ResearchStore

_LOCK = threading.Lock()
_OCR_LOCK = threading.Lock()
_OCR_ENGINE = None
MAX_FILE = 30_000_000
MAX_TOTAL = 500_000_000
MAX_FILES = 2000
TEXT_TYPES = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".eml"}
OFFICE_TYPES = {".xlsx", ".pptx"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
SUPPORTED = TEXT_TYPES | OFFICE_TYPES | IMAGE_TYPES


def _ocr_image(image) -> str:
    """Read text locally from a PIL image using RapidOCR/ONNX Runtime."""
    global _OCR_ENGINE
    from PIL import Image
    import numpy as np

    if image.width * image.height > 40_000_000:
        raise ValueError("Image exceeds the 40 megapixel OCR limit")
    image = image.convert("RGB")
    image.thumbnail((4000, 4000))
    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            try:
                from rapidocr import RapidOCR
                _OCR_ENGINE = RapidOCR()
            except ImportError as exc:
                raise ValueError("OCR is not installed; install ProSe with the [ocr] extra") from exc
        result = _OCR_ENGINE(np.asarray(image))
    lines = getattr(result, "txts", None) or []
    return "\n".join(str(line).strip() for line in lines if str(line).strip())


def _ocr_pdf_page(page) -> str:
    pixmap = page.get_pixmap(matrix=__import__("fitz").Matrix(2, 2), alpha=False)
    from PIL import Image

    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return _ocr_image(image)


def case_text(name: str, content: bytes) -> tuple[list[tuple[str, str]], list[str]]:
    suffix = Path(name).suffix.lower()
    warnings = []
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > 1000:
            raise ValueError("PDF exceeds 1000-page OCR limit")
        sections = []
        ocr_count = 0
        try:
            import fitz

            pdf = fitz.open(stream=content, filetype="pdf")
        except ImportError:
            pdf = None
        try:
            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip() and pdf is not None:
                    text = _ocr_pdf_page(pdf.load_page(i - 1))
                    if text.strip():
                        ocr_count += 1
                sections.append((f"PDF page {i}", text))
        finally:
            if pdf is not None:
                pdf.close()
        empty = sum(not text.strip() for _, text in sections)
        if ocr_count:
            warnings.append(f"OCR extracted text from {ocr_count} scanned PDF page(s) locally.")
        if empty:
            warnings.append(f"{empty} PDF page(s) had no readable text, even after OCR.")
    elif suffix in IMAGE_TYPES:
        try:
            from PIL import Image
            import pillow_heif

            pillow_heif.register_heif_opener()
            image = Image.open(io.BytesIO(content))
            text = _ocr_image(image)
        except ImportError as exc:
            raise ValueError("Image OCR requires the [ocr] extra") from exc
        sections = [("OCR image text", text)]
        if text.strip():
            warnings.append("Text extracted from image locally using OCR; verify names and numbers.")
    elif suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(content)) as doc:
            xml_name = "word/document.xml"
            if doc.getinfo(xml_name).file_size > MAX_FILE:
                raise ValueError("Expanded Word document exceeds size limit")
            root = ElementTree.fromstring(doc.read(xml_name))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = ["".join(t.text or "" for t in p.findall(".//w:t", ns))
                      for p in root.findall(".//w:p", ns)]
        sections = [("Word document body", "\n".join(paragraphs))]
        warnings.append("Word body text only; images, comments and attachments are omitted.")
    elif suffix == ".pptx":
        with zipfile.ZipFile(io.BytesIO(content)) as deck:
            names = sorted((n for n in deck.namelist()
                            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
            if len(names) > 500:
                raise ValueError("Presentation exceeds 500 slides")
            sections = []
            for number, name in enumerate(names, 1):
                if deck.getinfo(name).file_size > MAX_FILE:
                    raise ValueError("Expanded presentation slide exceeds size limit")
                root = ElementTree.fromstring(deck.read(name))
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                lines = ["".join(t.text or "" for t in p.findall(".//a:t", ns))
                         for p in root.findall(".//a:p", ns)]
                sections.append((f"Slide {number}", "\n".join(x for x in lines if x.strip())))
        warnings.append("Slide text only; images, notes and animations are omitted.")
    elif suffix == ".xlsx":
        from xml.etree.ElementTree import ParseError

        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
              "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
              "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
        with zipfile.ZipFile(io.BytesIO(content)) as book:
            shared = []
            if "xl/sharedStrings.xml" in book.namelist():
                root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in si.findall(".//m:t", ns))
                          for si in root.findall("m:si", ns)]
            workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
            rels = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
            targets = {r.get("Id"): r.get("Target") for r in rels.findall("p:Relationship", ns)}
            sheets = workbook.findall("m:sheets/m:sheet", ns)
            if len(sheets) > 250:
                raise ValueError("Workbook exceeds 250 sheets")
            sections = []
            for sheet in sheets:
                target = targets.get(sheet.get("{" + ns["r"] + "}id"), "")
                target = target.lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                if target not in book.namelist() or not target.endswith(".xml"):
                    raise ValueError("Workbook contains an invalid worksheet reference")
                if book.getinfo(target).file_size > MAX_FILE:
                    raise ValueError("Expanded worksheet exceeds size limit")
                try:
                    root = ElementTree.fromstring(book.read(target))
                except ParseError as exc:
                    raise ValueError("Workbook worksheet XML could not be read") from exc
                rows = []
                for row in root.findall(".//m:sheetData/m:row", ns):
                    values = []
                    for cell in row.findall("m:c", ns):
                        value = cell.find("m:v", ns)
                        text = value.text if value is not None else ""
                        if cell.get("t") == "s" and text.isdigit():
                            text = shared[int(text)] if int(text) < len(shared) else text
                        elif cell.get("t") == "inlineStr":
                            text = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
                        if text:
                            values.append(f"{cell.get('r', '')}={text}")
                    if values:
                        rows.append(" | ".join(values))
                sections.append(("Sheet: " + sheet.get("name", "Unnamed"), "\n".join(rows)))
        warnings.append("Cell values only. Formula results, formatting, charts, and "
                         "images are omitted.")
    elif suffix == ".eml":
        message = BytesParser(policy=policy.default).parsebytes(content)
        headers = "\n".join(f"{k}: {message.get(k, '')}"
                            for k in ("Date", "From", "To", "Subject"))
        body = message.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        if body and body.get_content_type() == "text/html":
            from bs4 import BeautifulSoup

            text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
        sections = [("Email headers and body", headers + "\n\n" + text)]
        if any(message.iter_attachments()):
            warnings.append("Email attachments were not imported; save them as separate files.")
    elif suffix in SUPPORTED:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("utf-16") if content.startswith((b"\xff\xfe", b"\xfe\xff")) \
                else content.decode("cp1252", errors="replace")
        sections = [("Text document", text)]
    else:
        raise ValueError(f"Unsupported file type {suffix or '(none)'}; provide PDF, DOCX or text")
    if not any(text.strip() for _, text in sections):
        raise ValueError("No readable text; this may be a scan requiring OCR")
    return sections, warnings


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and not re.match(r"^[A-Za-z]:", name)


def import_case_folder(store: ResearchStore) -> dict:
    if not _LOCK.acquire(blocking=False):
        raise ValueError("A case import is already running")
    try:
        return _import_case_folder(store)
    finally:
        _LOCK.release()


def _import_case_folder(store: ResearchStore) -> dict:
    folder = (store.directory / "scouting-case").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    total_bytes, total_files = 0, 0
    results = []

    def import_one(name: str, content: bytes) -> None:
        meta = {"url": "case://scouting-case/" + quote(name, safe="/"),
                "title": name, "category": "Your case documents", "kind": "case",
                "pack": "scouting-case", "status": "unavailable",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "edition": "User-supplied file; document date may differ from import date",
                "scope_note": "Private case material. Correspondence and allegations are not "
                              "established facts or national policy. "
                              "Verify the author, date and scope.",
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        try:
            sections, warnings = case_text(name, content)
            meta.update(status="ready", extraction_warnings=warnings)
        except Exception as exc:
            sections = []
            meta["error"] = f"{type(exc).__name__}: {exc}"[:300]
        store.ingest(meta, sections)
        results.append({"name": name, "status": meta["status"],
                        "warnings": meta.get("extraction_warnings", []),
                        "error": meta.get("error", "")})

    def reserve(name: str, size: int) -> bool:
        nonlocal total_bytes, total_files
        total_files += 1
        total_bytes += size
        if (size > MAX_FILE or total_files > MAX_FILES or total_bytes > MAX_TOTAL
                or not _safe_name(name)):
            results.append({"name": name, "status": "skipped",
                            "error": "Unsafe archive path or import size/file limit reached"})
            return False
        return True

    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if not path.resolve().is_relative_to(folder):
            continue
        name = path.relative_to(folder).as_posix()
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as bundle:
                    for item in bundle.infolist():
                        if item.is_dir() or item.filename.startswith("__MACOSX/"):
                            continue
                        member = name + "/" + item.filename
                        if not _safe_name(item.filename):
                            results.append({"name": member, "status": "skipped",
                                            "error": "Unsafe archive path"})
                            continue
                        if not reserve(member, item.file_size):
                            continue
                        extension = Path(item.filename).suffix.lower()
                        if extension not in SUPPORTED:
                            results.append({"name": member, "status": "skipped",
                                            "error": "Unsupported format; import "
                                                      "nested ZIP separately"})
                            continue
                        try:
                            import_one(member, bundle.read(item))
                        except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
                            results.append({"name": member, "status": "skipped", "error": str(exc)})
            except (OSError, zipfile.BadZipFile) as exc:
                results.append({"name": name, "status": "skipped", "error": str(exc)})
        elif reserve(name, path.stat().st_size):
            if path.suffix.lower() in SUPPORTED:
                import_one(name, path.read_bytes())
            else:
                results.append({"name": name, "status": "skipped",
                                "error": "Unsupported file type; provide PDF, DOCX or text"})
    return {"folder": str(folder), "files": results,
            "ready": sum(r["status"] == "ready" for r in results),
            "incomplete": sum(r["status"] != "ready" for r in results)}
