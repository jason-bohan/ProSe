import re
import tempfile
import zipfile
import zlib
from contextlib import suppress
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".json", ".jsonl", ".csv", ".pdf"}
SKIP_DIR_NAMES = {"system volume information", "$recycle.bin", "lost+found"}
MAX_FILES = 1000
MAX_MEMBER_BYTES = 100_000_000

_STREAM_RE = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.S)
_SIMPLE_ESCAPES = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12}


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    backslash = ord("\\")
    while i < len(raw):
        ch = raw[i]
        if ch != backslash:
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            break
        nxt = raw[i]
        if nxt in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[nxt])
            i += 1
        elif 48 <= nxt <= 55:
            j = i
            while j < len(raw) and j < i + 3 and 48 <= raw[j] <= 55:
                j += 1
            out.append(int(raw[i:j], 8) & 0xFF)
            i = j
        elif nxt in (10, 13):
            i += 1
            if nxt == 13 and i < len(raw) and raw[i] == 10:
                i += 1
        else:
            out.append(nxt)
            i += 1
    return bytes(out)


def _is_textish(text: str) -> bool:
    if not text.strip():
        return False
    bad = sum(1 for c in text if not (c.isprintable() or c in "\n\r\t"))
    return bad * 5 <= len(text)


def _paren_strings(payload: bytes) -> list[bytes]:
    out: list[bytes] = []
    i = 0
    size = len(payload)
    while i < size:
        if payload[i] != 40:
            i += 1
            continue
        depth = 1
        j = i + 1
        buf = bytearray()
        while j < size and depth:
            ch = payload[j]
            if ch == 92 and j + 1 < size:
                buf.append(ch)
                buf.append(payload[j + 1])
                j += 2
                continue
            if ch == 40:
                depth += 1
            elif ch == 41:
                depth -= 1
                if depth == 0:
                    break
            buf.append(ch)
            j += 1
        if depth == 0:
            out.append(bytes(buf))
            i = j + 1
        else:
            i += 1
    return out


def pdf_text(data: bytes) -> str:
    chunks: list[str] = []
    for match in _STREAM_RE.finditer(data):
        payload = match.group(1)
        with suppress(zlib.error):
            payload = zlib.decompress(payload)
        for token in _paren_strings(payload):
            text = _unescape(token).decode("latin-1")
            if _is_textish(text):
                chunks.append(text)
        chunks.append("\n")
    joined = "".join(chunks)
    return re.sub(r"[ \t]+", " ", joined).strip()


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        return pdf_text(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.strip()


def iter_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part.lower() in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        found.append(path)
        if len(found) >= MAX_FILES:
            break
    return found


def _extract_zip(source: Path, dest: Path) -> None:
    base = dest.resolve()
    with zipfile.ZipFile(source) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or info.file_size > MAX_MEMBER_BYTES:
                continue
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(base):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as src, target.open("wb") as out:
                out.write(src.read())


def _read_all(root: Path) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for path in iter_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        if text:
            items.append((path.stem.strip() or path.name, text))
    return items


def load(raw: str) -> list[tuple[str, str]]:
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("path is required")
    path = Path(cleaned).expanduser()
    if not path.exists():
        raise ValueError(f"no such path: {cleaned}")
    if path.is_file() and path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _extract_zip(path, root)
            return _read_all(root)
    if path.is_file():
        if path.suffix.lower() not in TEXT_EXTS:
            raise ValueError(f"unsupported file type: {path.suffix or 'none'}")
        text = read_text(path)
        return [(path.stem, text)] if text else []
    return _read_all(path)
