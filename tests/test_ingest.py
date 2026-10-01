from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest

from prose import ingest


def _mini_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "").replace("(", r"\(").replace(")", r"\)")
    payload = zlib.compress(b"BT /F1 12 Tf (" + escaped.encode("latin-1") + b") Tj ET")
    return (
        b"%PDF-1.4\n1 0 obj\n<< /Length "
        + str(len(payload)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + payload
        + b"\nendstream\nendobj\n%%EOF"
    )


def test_pdf_text_extracts_and_unescapes() -> None:
    text = ingest.pdf_text(_mini_pdf("Rule 30(b)(6) deposition of Jane Doe"))
    assert "30(b)(6)" in text
    assert "deposition of Jane Doe" in text


def test_pdf_text_balanced_parens_unescaped() -> None:
    stream = b"BT (admits (b) fully) Tj ET"
    data = b"%PDF-1.4\nstream\n" + stream + b"\nendstream\n%%EOF"
    assert "admits (b) fully" in ingest.pdf_text(data)


def test_pdf_text_without_streams_is_empty() -> None:
    assert ingest.pdf_text(b"binary \x00\x01 noise") == ""


def test_load_folder_walks_and_filters(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "System Volume Information").mkdir()
    (tmp_path / "answer.txt").write_text(
        "the answer admits paragraph 3", encoding="utf-8"
    )
    (tmp_path / "sub" / "rq.md").write_text(
        "request for production [[answer]]", encoding="utf-8"
    )
    (tmp_path / "skip.bin").write_bytes(b"\x00\x01")
    (tmp_path / ".hidden.txt").write_text("hidden", encoding="utf-8")
    (tmp_path / "System Volume Information" / "idx.txt").write_text("sys", encoding="utf-8")
    items = dict(ingest.load(str(tmp_path)))
    assert set(items) == {"answer", "rq"}
    assert "[[answer]]" in items["rq"]


def test_load_zip(tmp_path: Path) -> None:
    zpath = tmp_path / "production.zip"
    with zipfile.ZipFile(zpath, "w") as bundle:
        bundle.writestr("interrogatory.txt", "interrogatory no. 1")
        bundle.writestr("../escape.txt", "should be dropped")
    items = ingest.load(str(zpath))
    assert items == [("interrogatory", "interrogatory no. 1")]


def test_load_single_pdf(tmp_path: Path) -> None:
    path = tmp_path / "motion.pdf"
    path.write_bytes(_mini_pdf("motion to compel discovery"))
    items = ingest.load(str(path))
    assert items == [("motion", "motion to compel discovery")]


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="path is required"):
        ingest.load("   ")
    with pytest.raises(ValueError, match="no such path"):
        ingest.load("definitely-not-a-real-path-xyz")
    png = tmp_path / "photo.png"
    png.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(ValueError, match="unsupported"):
        ingest.load(str(png))
