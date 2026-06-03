from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3
import time
from urllib import request
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


MAX_EXTRACTED_CHARS = 24_000


@dataclass(frozen=True)
class ProjectMaterial:
    id: int
    telegram_id: int
    source_type: str
    title: str
    content: str
    source_url: str | None
    file_path: str | None
    created_at: int


class ProjectMaterials:
    def __init__(self, db_path: Path, files_dir: Path) -> None:
        self.db_path = db_path
        self.files_dir = files_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS project_materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    file_path TEXT,
                    created_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_materials_user ON project_materials(telegram_id, id)"
            )

    def add_material(
        self,
        telegram_id: int,
        source_type: str,
        title: str,
        content: str,
        *,
        source_url: str | None = None,
        file_path: Path | None = None,
    ) -> int:
        now = int(time.time())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_materials (telegram_id, source_type, title, content, source_url, file_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    source_type,
                    title,
                    trim_text(content, MAX_EXTRACTED_CHARS),
                    source_url,
                    str(file_path) if file_path else None,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def get_recent_materials(self, telegram_id: int, limit: int) -> list[ProjectMaterial]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, telegram_id, source_type, title, content, source_url, file_path, created_at
                FROM project_materials
                WHERE telegram_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_id, limit),
            ).fetchall()
        return [
            ProjectMaterial(
                id=int(row[0]),
                telegram_id=int(row[1]),
                source_type=str(row[2]),
                title=str(row[3]),
                content=str(row[4]),
                source_url=str(row[5]) if row[5] else None,
                file_path=str(row[6]) if row[6] else None,
                created_at=int(row[7]),
            )
            for row in rows
        ]

    def count_materials(self, telegram_id: int | None = None) -> int:
        with self._connect() as connection:
            if telegram_id is None:
                row = connection.execute("SELECT COUNT(*) FROM project_materials").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM project_materials WHERE telegram_id = ?",
                    (telegram_id,),
                ).fetchone()
        return int(row[0])

    def clear_user_materials(self, telegram_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM project_materials WHERE telegram_id = ?", (telegram_id,))


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return normalize_whitespace(" ".join(self.parts))


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>]+", text)
    return [url.rstrip(".,);]") for url in urls]


def fetch_url_text(url: str, timeout_seconds: int = 20) -> str:
    http_request = request.Request(
        url=url,
        headers={"User-Agent": "AIEngineeringPlatformBot/0.1"},
        method="GET",
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_EXTRACTED_CHARS * 4)
            content_type = response.headers.get("Content-Type", "")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"не удалось открыть ссылку: {exc}") from exc
    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or "<html" in text[:1000].lower():
        parser = _HTMLTextExtractor()
        parser.feed(text)
        return parser.text()
    return normalize_whitespace(text)


def extract_file_text(file_path: Path, original_name: str | None = None) -> str:
    suffix = (original_name or file_path.name).lower()
    if suffix.endswith(".docx"):
        return extract_docx_text(file_path)
    if suffix.endswith(".pptx"):
        return extract_pptx_text(file_path)
    if suffix.endswith((".txt", ".md", ".csv", ".tsv", ".log")):
        return file_path.read_text(encoding="utf-8", errors="replace")
    raise ValueError("поддерживаются .docx, .pptx, .txt, .md, .csv, .tsv и ссылки")


def extract_docx_text(file_path: Path) -> str:
    try:
        with ZipFile(file_path) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("не удалось прочитать Word .docx") from exc
    root = ElementTree.fromstring(xml)
    texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    return normalize_whitespace("\n".join(texts))


def extract_pptx_text(file_path: Path) -> str:
    try:
        with ZipFile(file_path) as archive:
            slide_names = sorted(
                name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            slides: list[str] = []
            for index, slide_name in enumerate(slide_names, start=1):
                root = ElementTree.fromstring(archive.read(slide_name))
                texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
                if texts:
                    slides.append(f"Слайд {index}: " + " ".join(texts))
    except BadZipFile as exc:
        raise ValueError("не удалось прочитать PowerPoint .pptx") from exc
    return normalize_whitespace("\n".join(slides))


def normalize_whitespace(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def trim_text(text: str, limit: int) -> str:
    normalized = normalize_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "\n...[текст обрезан]"
