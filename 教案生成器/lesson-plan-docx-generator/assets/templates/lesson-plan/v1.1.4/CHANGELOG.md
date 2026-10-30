# Lesson Plan Template Package Changelog

## 1.1.4 - 2026-10-30 (optional visual qualification)

- Split the semantic lesson layout into overview/evaluation, implementation, and reflection tables while retaining all nine lesson stages and all evaluation rows and values.
- Promoted the implementation column labels to the first row of the implementation table and marked them as a repeated table header. Long activity rows can continue across pages; non-first-page headers provide the column labels in renderers that do not repeat the table row across a row continuation.
- Adjusted A4 margins so the fixed 9,918-twip lesson table fits within the printable area.
- Removed the no-wrap rule from evaluation remarks while retaining the v1.1.3 evaluation column widths and row pagination.
- Rebalanced the implementation table to give the student-activity column usable width, while keeping all five columns within the original table width; set body text to 10 pt so dense two-hour activities and reflection rows paginate without splitting a single activity across pages.
- Kept the final in-class summary, after-class section, and reflection together when they cross a page boundary, so the closing teaching sequence does not leave a reflection-only tail.
- The page-fit validator rejects fixed-layout tables wider than the printable body. Text is kept byte-for-byte literal; experimental zero-width line-break characters were removed because LibreOffice substituted the East Asian font after those markers.
- Added a non-first-page column-label guide because LibreOffice does not visibly repeat the DOCX implementation table's valid repeated-header row; the first page remains unchanged.
- Set an explicit East Asian font on the title run after full-page review found that theme font fallback omitted the L03 and L04 title text in LibreOffice-rendered PDFs.
- Changed the reflection rows to natural height, zero vertical cell padding, and 9.5 pt text so short reflections can remain with the preceding lesson content without removing any reflection text.
- This is an optional candidate. The default remains Template 1.1.2 pending separate Owner approval. Microsoft Word/WPS still requires native visual verification.
