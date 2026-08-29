# Importing local course PDFs

1. Copy a PDF into the repository's `data/` directory.
2. Start the app with `docker compose up --build` and open <http://localhost:8000>.
3. Select the PDF from the import panel.
4. Open the imported course and select **Review imports**.
5. Approve verified candidates. Only approved candidates appear in the roster and study sessions.
6. Use **Add person** for names the importer did not detect.

## Current parser behavior

The importer first extracts text from each PDF page. If that does not produce name candidates (as with the supplied scanned rosters), it renders the pages and runs local OCR, including a dedicated right-column pass for the name column. For the supported roster layout, it also crops the left-hand photo cell and saves it locally beside the detected person. It only proposes standalone name lines in either `Last, First` or `First Last` form. It records page count, extracted-text length, candidate count, and warnings in the local SQLite database.

This intentionally conservative first pass avoids turning arbitrary PDF text into people. It may find no candidates when the source is a scan, uses a table layout, or places the name next to other content. In those cases, add a few people manually and use the PDF to guide future parser improvements.

An identical PDF is detected by SHA-256 checksum and is not imported twice. Changed PDFs are treated as a new import until richer re-import matching is implemented.
