import hashlib
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from PIL import Image
import pytesseract

from .database import app_data_dir


NAME_PATTERNS = (
    re.compile(r"^\s*([A-Z][A-Za-z'\-]+),\s*([A-Z][A-Za-z'\-]+)\s*$"),
    re.compile(r"^\s*(?:Name\s*:\s*)?([A-Z][A-Za-z'\-]+)\s+([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})\s*$"),
)


def source_dir() -> Path:
    return Path(os.environ.get("FLASHCARDS_DATA_DIR", "data"))


def available_pdfs() -> list[dict]:
    root = source_dir()
    if not root.exists():
        return []
    return [
        {"filename": item.name, "size": item.stat().st_size}
        for item in sorted(root.glob("*.pdf"))
    ]


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        line = " ".join(line.split())
        for pattern_index, pattern in enumerate(NAME_PATTERNS):
            match = pattern.match(line)
            if not match:
                continue
            first, last = (match.group(2), match.group(1)) if pattern_index == 0 else match.groups()
            # Ignore all-caps headings such as the course code while retaining
            # multi-part names like "Daniel Ambrosio Palma" and "Ben de Hoyos".
            if not any(character.islower() for character in f"{first}{last}"):
                continue
            key = (first, last)
            if key not in seen:
                candidates.append(key)
                seen.add(key)
            break
    return candidates


def _positioned_candidates(image: Image.Image) -> list[tuple[str, str, int]]:
    """Read name lines from the right column and retain their page position."""
    right_edge = int(image.width * 0.45)
    right_column = image.crop((right_edge, 0, image.width, image.height))
    data = pytesseract.image_to_data(
        right_column, config="--psm 4", output_type=pytesseract.Output.DICT
    )
    lines: dict[tuple[int, int, int], list[tuple[str, int]]] = {}
    for index, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        lines.setdefault(key, []).append((word, data["top"][index]))

    result = []
    for words in lines.values():
        name = _candidates(" ".join(word for word, _ in words))
        if name:
            result.append((*name[0], sum(top for _, top in words) // len(words)))
    return result


def _row_fallback_candidates(image: Image.Image) -> list[tuple[str, str, int]]:
    """Read individual name cells when page-layout OCR misses a roster row."""
    right_column = image.crop((int(image.width * 0.50), 0, image.width, image.height))
    candidates = []
    # The supported roster template has three equally spaced name cells. Cropping
    # each one prevents one weak cell from affecting OCR of the entire page.
    for fraction in (0.216, 0.435, 0.655):
        center = int(image.height * fraction)
        cell = right_column.crop((0, center - int(image.height * 0.09), right_column.width, center + int(image.height * 0.09)))
        names = _candidates(pytesseract.image_to_string(cell, config="--psm 7"))
        if names:
            candidates.append((*names[0], center))
    return candidates


def _save_portrait(image: Image.Image, course_id: str, page_number: int, ordinal: int, name_y: int) -> str:
    """Save the photo cell to local application storage beside its detected name."""
    portrait_dir = app_data_dir() / "assets" / course_id
    portrait_dir.mkdir(parents=True, exist_ok=True)
    width, height = image.size
    crop = image.crop(
        (
            int(width * 0.10),
            max(0, name_y - int(height * 0.13)),
            int(width * 0.45),
            min(height, name_y + int(height * 0.13)),
        )
    ).convert("RGB")
    filename = f"page-{page_number:02d}-person-{ordinal:02d}.jpg"
    crop.save(portrait_dir / filename, "JPEG", quality=88, optimize=True)
    return f"{course_id}/{filename}"


def _ocr_pdf(path: Path, course_id: str) -> tuple[str, int, list[dict]]:
    """Render image-based PDFs locally, then OCR them page by page."""
    with tempfile.TemporaryDirectory(prefix="flashcards-ocr-") as directory:
        output_prefix = Path(directory) / "page"
        subprocess.run(
            ["pdftoppm", "-r", "220", "-png", str(path), str(output_prefix)],
            check=True,
            capture_output=True,
            text=True,
        )
        pages = sorted(Path(directory).glob("page-*.png"))
        page_text = []
        candidates = []
        seen: set[tuple[str, str]] = set()
        for page_number, page in enumerate(pages, start=1):
            with Image.open(page) as image:
                # These roster PDFs place the name in a clean right-hand column.
                # OCR that region separately because face photos and table rules make
                # whole-page OCR significantly less reliable.
                right_column = image.crop((int(image.width * 0.45), 0, image.width, image.height))
                page_text.append(pytesseract.image_to_string(image, config="--psm 6"))
                page_text.append(pytesseract.image_to_string(right_column, config="--psm 4"))
                detected = _positioned_candidates(image)
                if len(detected) < 3:
                    detected.extend(_row_fallback_candidates(image))
                for ordinal, (first_name, last_name, name_y) in enumerate(detected, start=1):
                    key = (first_name, last_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        {
                            "first_name": first_name,
                            "last_name": last_name,
                            "image_path": _save_portrait(image, course_id, page_number, ordinal, name_y),
                        }
                    )
        text = "\n".join(page_text)
        return text, len(pages), candidates


def import_pdf(filename: str, conn) -> dict:
    path = (source_dir() / filename).resolve()
    if path.parent != source_dir().resolve() or path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("Choose a PDF from the local data directory.")

    checksum = _checksum(path)
    existing = conn.execute(
        """
        SELECT id, title,
               (SELECT COUNT(*) FROM cards WHERE course_id = courses.id) AS card_count,
               (SELECT COUNT(*) FROM cards WHERE course_id = courses.id AND reviewed = 1) AS approved_count,
               (SELECT COUNT(*) FROM review_events
                  JOIN cards ON cards.id = review_events.card_id
                  WHERE cards.course_id = courses.id) AS review_count
        FROM courses WHERE source_checksum = ?
        """,
        (checksum,),
    ).fetchone()
    course_id = existing["id"] if existing else f"course-{uuid.uuid4().hex[:12]}"
    title = existing["title"] if existing else path.stem.replace("_", " ")

    started_at = datetime.now(timezone.utc).isoformat()
    run = conn.execute(
        "INSERT INTO import_runs (source_filename, source_checksum, started_at, status) VALUES (?, ?, ?, 'running')",
        (filename, checksum, started_at),
    )
    try:
        reader = PdfReader(str(path))
        embedded_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        candidates = [
            {"first_name": first_name, "last_name": last_name, "image_path": None}
            for first_name, last_name in _candidates(embedded_text)
        ]
        text = embedded_text
        ocr_pages = 0
        if not candidates:
            ocr_text, ocr_pages, candidates = _ocr_pdf(path, course_id)
            text = f"{embedded_text}\n{ocr_text}"
        now = datetime.now(timezone.utc).isoformat()
        if not existing:
            conn.execute(
                "INSERT INTO courses (id, title, source_filename, source_checksum, imported_at) VALUES (?, ?, ?, ?, ?)",
                (course_id, title, filename, checksum, now),
            )
        existing_cards = {
            (row["first_name"], row["last_name"]): row["id"]
            for row in conn.execute("SELECT id, first_name, last_name FROM cards WHERE course_id = ?", (course_id,))
        }
        added = 0
        for candidate in candidates:
            key = (candidate["first_name"], candidate["last_name"])
            if key in existing_cards:
                if candidate["image_path"]:
                    conn.execute("UPDATE cards SET image_path = ? WHERE id = ?", (candidate["image_path"], existing_cards[key]))
                continue
            card_id = f"{course_id}-card-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO cards (id, course_id, first_name, last_name, image_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (card_id, course_id, candidate["first_name"], candidate["last_name"], candidate["image_path"], now),
            )
            conn.execute("INSERT INTO card_progress (card_id) VALUES (?)", (card_id,))
            added += 1
        warning = None
        if not candidates:
            warning = "No high-confidence name lines were found, even after local OCR. Add cards manually or improve the importer for this PDF layout."
        conn.execute(
            "UPDATE import_runs SET finished_at = ?, status = 'complete', pages = ?, extracted_text_length = ?, candidate_count = ?, warning = ? WHERE id = ?",
            (now, len(reader.pages), len(text), len(candidates), warning, run.lastrowid),
        )
        return {"status": "updated" if existing else "imported", "course_id": course_id, "title": title, "pages": len(reader.pages), "ocr_pages": ocr_pages, "cards": len(candidates), "added": added, "warning": warning}
    except Exception as exc:
        conn.execute(
            "UPDATE import_runs SET finished_at = ?, status = 'failed', warning = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), str(exc), run.lastrowid),
        )
        raise
