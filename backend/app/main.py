import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import app_data_dir, connection, initialize_database
from .importer import available_pdfs, import_pdf
from .study import adaptive_cards, update_memory_state


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
ASSETS = app_data_dir() / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Local Flashcards")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


class ImportRequest(BaseModel):
    filename: str


class CreateCardRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    facts: list[str] = []


class StartSessionRequest(BaseModel):
    mode: str
    limit: int = Field(default=15, ge=1, le=200)


class ReviewRequest(BaseModel):
    card_id: str
    result: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def card_row(row) -> dict:
    item = dict(row)
    item["facts"] = json.loads(item["facts"]) if item["facts"] else []
    return item


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/imports/available")
def imports_available():
    return available_pdfs()


@app.post("/api/imports")
def create_import(request: ImportRequest):
    with connection() as conn:
        try:
            return import_pdf(request.filename, conn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"PDF import failed: {exc}") from exc


@app.get("/api/courses")
def courses():
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(DISTINCT cards.id) AS card_count,
                   MAX(s.ended_at) AS last_studied_at
            FROM courses c
            LEFT JOIN cards ON cards.course_id = c.id AND cards.reviewed = 1
            LEFT JOIN study_sessions s ON s.course_id = c.id
            WHERE c.active = 1
            GROUP BY c.id
            ORDER BY c.imported_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/courses/{course_id}")
def course(course_id: str):
    with connection() as conn:
        item = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Course not found")
        return dict(item)


@app.get("/api/courses/{course_id}/cards")
def cards(course_id: str, sort: str = "last"):
    sort_columns = {
        "first": "cards.first_name, cards.last_name",
        "last": "cards.last_name, cards.first_name",
        "confidence": "progress.mastery ASC, progress.seen_count ASC, cards.last_name, cards.first_name",
    }
    column = sort_columns.get(sort, sort_columns["first"])
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT cards.*, progress.seen_count, progress.right_count, progress.wrong_count,
                   progress.mastery, progress.stability_days, progress.last_reviewed_at
            FROM cards JOIN card_progress progress ON progress.card_id = cards.id
            WHERE cards.course_id = ? AND cards.reviewed = 1
            ORDER BY {column}
            """,
            (course_id,),
        ).fetchall()
        return [card_row(row) for row in rows]


@app.get("/api/courses/{course_id}/candidates")
def candidates(course_id: str):
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM cards WHERE course_id = ? AND reviewed = 0 ORDER BY last_name, first_name",
            (course_id,),
        ).fetchall()
        return [card_row(row) for row in rows]


@app.get("/api/courses/{course_id}/stats")
def course_stats(course_id: str):
    with connection() as conn:
        course_exists = conn.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course_exists:
            raise HTTPException(status_code=404, detail="Course not found")
        totals = conn.execute(
            """
            SELECT COUNT(review_events.id) AS reviews,
                   COALESCE(SUM(CASE WHEN review_events.result = 'right' THEN 1 ELSE 0 END), 0) AS right_count,
                   COALESCE(SUM(CASE WHEN review_events.result = 'wrong' THEN 1 ELSE 0 END), 0) AS wrong_count,
                   COUNT(DISTINCT study_sessions.id) AS session_count
            FROM study_sessions
            LEFT JOIN review_events ON review_events.session_id = study_sessions.id
            WHERE study_sessions.course_id = ?
            """,
            (course_id,),
        ).fetchone()
        return dict(totals)


@app.post("/api/courses/{course_id}/cards")
def create_card(course_id: str, request: CreateCardRequest):
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Course not found")
        card_id = f"{course_id}-card-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO cards (id, course_id, first_name, last_name, facts, reviewed, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (card_id, course_id, request.first_name.strip(), request.last_name.strip(), json.dumps(request.facts), now()),
        )
        conn.execute("INSERT INTO card_progress (card_id) VALUES (?)", (card_id,))
        return {"id": card_id}


@app.post("/api/courses/{course_id}/candidates/{card_id}/approve")
def approve_candidate(course_id: str, card_id: str):
    with connection() as conn:
        updated = conn.execute(
            "UPDATE cards SET reviewed = 1 WHERE id = ? AND course_id = ?", (card_id, course_id)
        )
        if not updated.rowcount:
            raise HTTPException(status_code=404, detail="Candidate card not found")
        return {"status": "approved"}


@app.post("/api/courses/{course_id}/sessions")
def start_session(course_id: str, request: StartSessionRequest):
    if request.mode not in {"all", "adaptive", "morris"}:
        raise HTTPException(status_code=400, detail="Mode must be all, adaptive, or morris")
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT cards.*, progress.seen_count, progress.right_count, progress.wrong_count,
                   progress.mastery, progress.stability_days, progress.last_reviewed_at
            FROM cards JOIN card_progress progress ON progress.card_id = cards.id
            WHERE cards.course_id = ? AND cards.reviewed = 1
            """,
            (course_id,),
        ).fetchall()
        cards_to_choose = [card_row(row) for row in rows]
        if not cards_to_choose:
            raise HTTPException(status_code=400, detail="Approve or add cards before starting a session")
        if request.mode == "all":
            import random
            random.shuffle(cards_to_choose)
            selected = cards_to_choose
        else:
            selected = adaptive_cards(cards_to_choose, request.limit)
        session_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO study_sessions (id, course_id, mode, started_at, selected_count) VALUES (?, ?, ?, ?, ?)",
            (session_id, course_id, request.mode, now(), len(selected)),
        )
        return {"id": session_id, "mode": request.mode, "cards": selected}


@app.post("/api/sessions/{session_id}/reviews")
def review(session_id: str, request: ReviewRequest):
    if request.result not in {"right", "wrong"}:
        raise HTTPException(status_code=400, detail="Result must be right or wrong")
    with connection() as conn:
        session = conn.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        card = conn.execute(
            "SELECT p.* FROM card_progress p JOIN cards c ON c.id = p.card_id WHERE p.card_id = ? AND c.course_id = ?",
            (request.card_id, session["course_id"]),
        ).fetchone()
        if not card:
            raise HTTPException(status_code=400, detail="Card is not part of this course")
        reviewed_at = now()
        right_increment = 1 if request.result == "right" else 0
        wrong_increment = 1 if request.result == "wrong" else 0
        updated_memory = update_memory_state(dict(card), request.result, datetime.fromisoformat(reviewed_at))
        conn.execute(
            """
            UPDATE card_progress
            SET seen_count = seen_count + 1, right_count = right_count + ?, wrong_count = wrong_count + ?,
                confidence = ?, mastery = ?, stability_days = ?, last_reviewed_at = ?, last_result = ?
            WHERE card_id = ?
            """,
            (right_increment, wrong_increment, updated_memory["mastery"], updated_memory["mastery"], updated_memory["stability_days"], reviewed_at, request.result, request.card_id),
        )
        conn.execute(
            "INSERT INTO review_events (session_id, card_id, reviewed_at, result) VALUES (?, ?, ?, ?)",
            (session_id, request.card_id, reviewed_at, request.result),
        )
        conn.execute(
            "UPDATE study_sessions SET reviewed_count = reviewed_count + 1, right_count = right_count + ?, wrong_count = wrong_count + ? WHERE id = ?",
            (right_increment, wrong_increment, session_id),
        )
        return {"status": "recorded"}


@app.post("/api/sessions/{session_id}/complete")
def complete_session(session_id: str):
    with connection() as conn:
        conn.execute("UPDATE study_sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?", (now(), session_id))
        session = conn.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return dict(session)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
