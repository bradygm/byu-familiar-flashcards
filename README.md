# Familiar

**Familiar** is a local, Docker-first flashcard app for learning the people in a course. It imports the PDF roster exported by [BYU Flashcards](https://flashcards.byu.edu), extracts the names and portraits, and keeps each course's cards and study history on your machine.

It was built for the part of a semester that conventional flashcard apps do not handle especially well: quickly learning the names and faces of everyone in a room, then coming back for a low-friction refresher later. There are no forced due dates. You choose a course, start a useful session, and the app decides what deserves attention.

> **Privacy note:** roster PDFs and study history are local. `data/` and `app-data/` are ignored by Git. Do not commit or publish real roster PDFs, portraits, or the local SQLite database.

## Screenshot

_A screenshot using fictional/demo roster data will be added here before the first public release._

## Quick start

1. Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Export a course roster PDF from BYU Flashcards (instructions below) and put it in `data/`.
3. Start the app from this directory:

   ```bash
   docker compose up --build
   ```

4. Open <http://localhost:8000>.
5. Import the PDF, review the candidates, and approve the people to include in study sessions.

The only exposed port is local port 8000. Stop the app with `docker compose down`; this preserves `app-data/`. Removing `app-data/` removes imported courses and progress.

## Exporting a BYU Flashcards roster

Familiar expects the roster-style PDF exported by [BYU Flashcards](https://flashcards.byu.edu).

1. Open the course in BYU Flashcards.
2. Find and select **Export**.
3. Choose **3 students per page**.
4. Download the PDF and copy it into this repository's `data/` directory.
5. Import it from Familiar's home page.

Keep one exported PDF per course. You can retain PDFs from previous semesters, import each as its own course, and review any course independently.

## Study modes

All modes are intentionally **no-deadline**: every approved card remains available whenever you sit down to study.

| Mode | What it does | Best for |
| --- | --- | --- |
| **Adaptive review** | Selects a varied set with an emphasis on people with low predicted recall, newly imported people, and uncertain estimates. | A quick, helpful session when you do not want to decide what to study. |
| **Expanding recall** | Starts with an adaptively chosen base set (up to 15 people), then brings a correctly recalled person back after increasingly large within-session gaps. A miss returns sooner. The session is capped. | Rapidly learning a smaller group at the beginning of a semester. |
| **All cards** | Shows every approved person once in a fresh random order. | A broad check-in or a refresher later in the semester. |

Expanding recall is inspired by retrieval-practice research rather than an attempt to reproduce a commercial spaced-repetition scheduler. In a study of face-name learning, Morris and colleagues found substantially better later name recall from retrieval practice on an expanding schedule than from restudying on the same schedule: [Morris et al., 2005, *Strategies for learning proper names: expanding retrieval practice, meaning and imagery*](https://doi.org/10.1002/acp.1115). Familiar uses that idea inside one finite session: after a correct answer, it schedules another attempt after 3, then 7 intervening reviews; after the third correct answer, the card leaves that session. A wrong answer returns after 2 intervening reviews.

The paper supports the use of repeated retrieval for learning names; it does **not** validate Familiar's particular gap sizes, cap, or scoring coefficients. Those are deliberately simple product choices that can be revised with real usage data.

## How adaptive selection works

Each card stores two local estimates:

- \(M\), **mastery**, the card's current recall strength;
- \(S\), **stability** in days, how slowly that strength fades.

If \(d\) days have passed since the last review, Familiar estimates current recall probability as:

$$
\hat p = \operatorname{clamp}_{0.01}^{0.99}\!\left(M e^{-d / \max(S, 0.02)}\right).
$$

This is a transparent heuristic, not a scientifically calibrated model of an individual learner. It prevents two unwanted behaviors: treating a card as permanently learned after one success, and hiding a card because it has no arbitrary “due” date.

For a candidate card with \(n\) previous attempts, its adaptive priority is:

$$
\text{priority} = 2.2\,\mathbf{1}_{n=0} + 3(1-\hat p) + \frac{0.55}{\sqrt{n+1}} + \varepsilon,
\qquad 0 \le \varepsilon < 0.25.
$$

The new-card term gets people into the first sessions; the predicted-recall term brings likely-forgotten people forward; the uncertainty term makes the app sample cards it has not measured much. The small random term avoids the same rigid ordering every time. About 80% of an adaptive session comes from the highest-priority cards and the remainder is sampled from the rest, keeping familiar people in the mix.

After each answer, the estimates update as follows. A correct answer earns a larger gain when the retrieval was harder:

$$
\begin{aligned}
M' &= \min\!\left(0.98,\; M + (1-M)\bigl[0.22 + 0.18(1-\hat p)\bigr]\right),\\
S' &= \min\!\left(120,\; S\bigl[1.45 + 0.70(1-\hat p)\bigr] + 0.03\right).
\end{aligned}
$$

A wrong answer reduces both estimates so the card will be selected sooner:

$$
M' = \max(0.05, 0.55M),
\qquad
S' = \max(0.02, 0.42S).
$$

For example, a brand-new card begins with a conservative prior rather than 0% or 100%. This means its visible strength is an estimate that becomes more individualized with every answer—not simply `correct / total`.

## Controls

- `Space` or `Enter`: flip a card
- `R`: mark right (before or after flipping)
- `W`: mark wrong (after flipping)
- `Esc`: end the current session

## Data and import behavior

The importer first reads embedded PDF text. For scanned rosters, it renders pages and runs local OCR on the name column. It records the source-file checksum, so importing an unchanged PDF will not create duplicates. Review and approve candidates before they appear in study sessions; missed names can be added manually from the course page.

The application stores courses, cards, progress, sessions, and review events in SQLite under the gitignored `app-data/` directory. The PDFs remain in the gitignored `data/` directory.

## Current limitations

- The BYU 3-students-per-page export is the supported layout; PDF formats vary and may need importer work.
- There is not yet a database backup/export command.
- The study model is a small, inspectable heuristic, not an implementation of Anki or a validated memory model.
