# Lesson Plan Template Package Changelog

## 1.1.0 - 2026-08-01

- Added 70 versioned Word semantic bookmarks to the unchanged v1.0.0 DOCX package.
- Added semantic anchors for fixed fields, all writable implementation cells, the three reflection cells, and the evaluation parent cell.
- Used Word-safe bookmark names no longer than 40 characters with stable short stage/column codes.
- Kept v1.0.0 and coordinate-based generation available through canonical or old compatibility template-only resolution, as well as explicit manifest selection.
- Added strict bookmark inventory, ID, pairing, story, start/end boundary, physical-container, output-preservation, and v1.0 visible/structure equivalence checks.
- Builder validation now checks the final temporary DOCX package across document, header, and footer stories before atomic replacement; failed validation leaves the target absent or unchanged.
- v1.1 semantic manifest fields are explicit and validated without fallback defaults; bookmark IDs are restricted to ASCII decimal digits.
