# Familiar - local flashcards

Familiar is a local web app for learning people from course PDFs. It uses a small FastAPI server and SQLite rather than browser storage. Raw PDFs stay in `data/`; imported course data and study history stay in the gitignored `app-data/` directory.

## Run it

1. Install and start Docker Desktop.
2. Place course PDFs in `data/`.
3. From this directory, run:

   ```bash
   docker compose up --build
   ```

4. Visit <http://localhost:8000>.

The only port exposed is local port 8000. Stop the service with `docker compose down`. This preserves `app-data/`; deleting that directory removes imported courses and progress.

## Importing courses

Choose a PDF on the home page. The importer first reads embedded PDF text; for scanned rosters it renders pages and runs local OCR on the name column. It marks high-confidence name lines as candidates. Review and approve candidates before they enter study sessions. Add missed names manually from the course page.

The importer records the source-file checksum and will not duplicate an unchanged PDF. PDF formats vary widely, so improving the import parser against real layouts is an expected next step.

## What works today

- Course discovery from the local `data/` folder and checksum-protected PDF import
- SQLite-persisted courses, candidates, cards, progress, sessions, and review events
- Candidate approval plus manual card entry
- Searchable roster with first/last-name sorting
- All-cards and no-deadline adaptive study sessions
- Mastery/stability-based adaptive selection and a capped expanding-recall session mode
- Keyboard controls: `Space` / `Enter` flip, `R` right, `W` wrong, `Esc` finish
- Per-course session, answer, accuracy, and miss statistics

## Current limitations

- Richer field extraction is not implemented yet. Portrait extraction currently supports the scanned roster layout used by the supplied PDFs (photo on the left, name on the right).
- There is not yet a database backup/export command.
- The app expects Docker Desktop's daemon to be running before it can start.
- Pictures bigger, rounded square not circle
