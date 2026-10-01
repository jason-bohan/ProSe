"""Download public official Scouting guides and index their full extracted text locally.

Run: python scripts/ingest_scouting.py [--refresh] [--directory PATH]
Install extraction dependencies: pip install -e ".[research]"
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose.research import ResearchStore, source_id  # noqa: E402

ALLOWED = {"www.scouting.org", "filestore.scouting.org", "scoutingwire.org",
           "troopleader.scouting.org", "uscode.house.gov", "tile.loc.gov",
           "iga.in.gov", "www.in.gov", "law.justia.com", "my.scouting.org"}
MAX_BYTES = 50_000_000


def normalized(url: str) -> str:
    url = urldefrag(url)[0]
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED or parts.username:
        raise ValueError("Source host is outside the public research allowlist")
    if parts.port not in (None, 443):
        raise ValueError("Unexpected source port")
    if parts.hostname.endswith("scouting.org") or parts.hostname == "scoutingwire.org":
        path = parts.path
        if not Path(path).suffix:
            path = path.rstrip("/") + "/"
        url = urlunparse(parts._replace(path=path, query=""))
    return url


def html_content(content: bytes) -> tuple[BeautifulSoup, list[tuple[str, str]], str]:
    soup = BeautifulSoup(content, "html.parser")
    root = (soup.select_one(".elementor-widget-theme-post-content")
            or soup.select_one(".entry-content") or soup.select_one("main")
            or soup.select_one("#content") or soup.body or soup)
    if len(root.get_text(" ", strip=True)) < 150:
        root = soup.select_one('[data-elementor-type="single-page"]') or root
    for tag in root.select("script, style, nav, header, footer, form, noscript"):
        tag.decompose()
    modified = soup.select_one('meta[property="article:modified_time"]')
    sections, label, lines = [], "Web page", []
    blocks = root.find_all(["h1", "h2", "h3", "h4", "p", "li", "table", "dt", "dd"])
    for block in blocks:
        if block.find_parent(["p", "li", "table", "dt", "dd"]) in blocks:
            continue
        text = block.get_text(" ", strip=True)
        if not text:
            continue
        if block.name in ("h1", "h2", "h3", "h4"):
            if lines:
                sections.append((label, "\n".join(lines)))
            label, lines = text[:220], [text]
        else:
            lines.append(text)
    if lines:
        sections.append((label, "\n".join(lines)))
    if sum(len(text) for _, text in sections) < 150:
        sections = [("Web page", root.get_text("\n", strip=True))]
    # Reject JavaScript shells/challenge pages instead of calling them ingested guides.
    full = " ".join(text for _, text in sections)
    if len(full) < 150 or "enable JavaScript to run this app" in full:
        raise ValueError("No readable document text (JavaScript shell or empty page)")
    return root, sections, modified.get("content", "") if modified else ""


def fetch(item: dict, cache: Path, refresh: bool) -> tuple[dict, list, list]:
    url = normalized(item["url"])
    meta = {**item, "url": url, "status": "unavailable",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "kind": item.get("kind", "policy")}
    if item.get("unavailable_reason"):
        return {**meta, "error": item["unavailable_reason"]}, [], []
    key = source_id(url)
    blob, record = cache / (key + ".bin"), cache / (key + ".json")
    try:
        if not refresh and blob.exists() and record.exists():
            content = blob.read_bytes()
            stored = json.loads(record.read_text(encoding="utf-8"))
            if hashlib.sha256(content).hexdigest() != stored["sha256"]:
                raise ValueError("Cached source checksum mismatch; run with --refresh")
            meta.update(stored)
        else:
            current = url
            for _ in range(6):
                with requests.get(current, timeout=(10, 45), stream=True, allow_redirects=False,
                                  headers={"User-Agent": "ProSe-Research/1.0"}) as response:
                    if response.is_redirect:
                        current = normalized(urljoin(current, response.headers["Location"]))
                        continue
                    response.raise_for_status()
                    parts, size = [], 0
                    for part in response.iter_content(65536):
                        size += len(part)
                        if size > MAX_BYTES:
                            raise ValueError("Document exceeded the 50 MB download limit")
                        parts.append(part)
                    content = b"".join(parts)
                    meta["resolved_url"] = current
                    meta["last_modified"] = response.headers.get("Last-Modified", "")
                    break
            else:
                raise ValueError("Too many source redirects")
            meta["sha256"] = hashlib.sha256(content).hexdigest()
            blob.write_bytes(content)
            record.write_text(json.dumps({k: meta[k] for k in (
                "fetched_at", "resolved_url", "last_modified", "sha256")}), encoding="utf-8")
        meta["bytes"] = len(content)
        links = []
        if content.startswith(b"%PDF"):
            reader = PdfReader(io.BytesIO(content))
            sections = [(f"PDF page {i}", re.sub(r"[\t \u00a0]+", " ", page.extract_text() or ""))
                        for i, page in enumerate(reader.pages, 1)]
            meta["pages"] = len(sections)
            empty = [label for label, text in sections if not text.strip()]
            meta["extraction_warnings"] = (
                [f"No text extracted on {len(empty)} page(s); inspect original for images/scans."]
                if empty else [])
            meta["format"] = "pdf"
        else:
            root, sections, modified = html_content(content)
            meta["web_modified"] = modified
            meta["format"] = "html"
            # Some official indexes place their child-guide links in a navigation
            # menu. Only the explicit follow prefixes may expand from that menu.
            anchors = root.select("a[href]")
            if item.get("follow"):
                anchors += [a for a in BeautifulSoup(content, "html.parser").select("a[href]")
                            if any(urljoin(url, a["href"]).startswith(prefix)
                                   for prefix in item["follow"])]
            for a in anchors:
                try:
                    target = normalized(urljoin(url, a["href"]))
                except ValueError:
                    continue
                path = urlparse(target).path
                pdf = path.lower().endswith(".pdf")
                follow = any(target.startswith(prefix) for prefix in item.get("follow", []))
                if (item.get("linked_pdfs") and pdf) or follow:
                    label = a.get_text(" ", strip=True)
                    if label.lower() in ("english", "spanish", "download", "pdf", "click here"):
                        parent = a.find_parent("li") or a.parent
                        label = parent.get_text(" ", strip=True)[:160] + " — " + label
                    links.append({"title": label or unquote(Path(path).name), "url": target,
                                  "category": item["category"], "kind": item.get("kind", "policy"),
                                  "discovered_from": url, "linked_pdfs": True,
                                  "follow": item.get("follow", []),
                                  "scope_note": "Linked by the official resource page; check the "
                                                "document's edition and scope before applying."})
        if sum(len(text.strip()) for _, text in sections) < 150:
            raise ValueError("No substantial extractable text; manual inspection/OCR required")
        meta["status"] = "ready"
        return meta, sections, links
    except (requests.RequestException, ValueError, OSError, KeyError) as exc:
        # Public-domain statutory text captured through the web reader when a mirror
        # rejects direct downloads. Preserve its 2025 edition and capture date.
        snapshot_path = (Path(__file__).resolve().parents[1]
                         / "prose/data/scouting_statutory_snapshots.json")
        snapshots = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if url in snapshots:
            snapshot = snapshots[url]
            text = snapshot["text"]
            meta.update(status="ready", format="text", fetched_at=snapshot["retrieved_at"],
                        edition=snapshot["edition"],
                        sha256=hashlib.sha256(text.encode()).hexdigest(),
                        acquisition="Browser-reader statutory snapshot; download unavailable",
                        extraction_warnings=["2025 mirror text; verify current official code."])
            return meta, [(snapshot["locator"], text)], []
        meta["error"] = str(exc)[:300]
        return meta, [], []
    except Exception as exc:
        # A malformed PDF must remain visible in the coverage report.
        meta["error"] = f"Extraction failed: {type(exc).__name__}: {exc}"[:300]
        return meta, [], []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    store = ResearchStore(args.directory)
    manifest_path = Path(__file__).resolve().parents[1] / "prose/data/scouting_sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cache = store.directory / "scouting" / "originals"
    cache.mkdir(parents=True, exist_ok=True)
    pending = manifest["sources"]
    seen = set()
    # Bounded breadth-first discovery from listed policy indexes, never a web-wide crawl.
    with ThreadPoolExecutor(max_workers=4) as pool:
        while pending:
            batch = []
            for item in pending:
                item["url"] = normalized(item["url"])
                if item["url"] not in seen:
                    seen.add(item["url"])
                    batch.append(item)
            if len(seen) > 600:
                raise ValueError("More than 600 sources discovered; review the manifest scope")
            pending = []
            for meta, sections, links in pool.map(lambda i: fetch(i, cache, args.refresh), batch):
                store.ingest(meta, sections)
                pending.extend(links)
                print(f"{meta['status']:11} {meta['title'][:85]}", flush=True)
            time.sleep(.2)
    report = store.catalog()
    (store.directory / "scouting" / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ready", "unavailable", "passages", "categories")}))


if __name__ == "__main__":
    main()
