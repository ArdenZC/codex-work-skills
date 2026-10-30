# Template 1.1.2 / 1.1.3 same-input comparison

## Inputs and outputs

- Content Contract: 2.4; same full input SHA-256: `E37EFF8E7880BEFB94D06D7ED9A22FF2449C6CA6BA89EBE14CBDD74AA90C126D`.
- Default 1.1.2 run: `issue73-quality-acceptance-r3`; template SHA-256: `6FFAFA579D3AACBC535BA624D0A6A766644868B0AF1FCE6AC37B20BA8F3D8FC1`.
- Candidate 1.1.3 run: `issue73-quality-acceptance-r3-v113`; template SHA-256: `D0A5BA37D2CB4AF445F10DE17FBC3363FA26E52C373B3F71EFE0E6C49C47D613`.
- Both are LibreOffice renders of the same Content bytes. The default and candidate L06 DOCX/PDF files and candidate L07/L11 PDFs are retained beside this record.

| L06 output | Pages | DOCX SHA-256 | PDF SHA-256 |
| --- | ---: | --- | --- |
| Template 1.1.2 | 9 | `e63220146e381c21fd0df55143fc1ba052cdd45af62e24f7c022f038ad7f4bc1` | `062c82fa966b23575b09e0da88a9e3154dd5b18016054f22656c932cf4477e58` |
| Template 1.1.3 | 7 | `207e745a0e5c06ca9c587eec87755581a07dacde63c7c72f59ba267e4c51f6a6` | `3fedb5502f377a9d24f83d58aeec5b9fdcb5e49f8891eeafe8eeae1457cbf872` |

## Visual findings and migration recommendation

On the same L06 input, 1.1.3 gives the evaluation remarks more horizontal room and reduces the rendered output from nine pages to seven. The remark column is easier to scan. This is a real improvement for long remarks.

The candidate still clips or overlaps the L07 p1 student-analysis cell and L11 p4 activity cells. The same failures are present in the default render. So 1.1.3 does not resolve the most serious readability defects in this course. Some continuation tables also lack repeated headers, and sparse tail pages remain.

**Recommendation:** retain Template 1.1.2 as the default for now. Consider a separate migration only after the candidate or a later template addresses the L07/L11 clipping and overlap and receives native Word/WPS validation. Native validation was unavailable in this audit: `WORD_WPS_UNVERIFIED`. LibreOfficeDev `26.8.0.0.alpha0` was used for PDF preview and is not a substitute for Word/WPS. Owner approval is required before any default migration.
