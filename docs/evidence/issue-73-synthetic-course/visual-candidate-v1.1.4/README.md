# Optional Template 1.1.4 visual candidate

This folder contains a same-input visual-remediation candidate for the synthetic 40-hour Content 2.4 course. It is not the default template; the generator still defaults to Template 1.1.2 until the Owner separately approves a migration.

## Generated artifacts

- 20 lesson DOCX files and 20 rendered PDFs, totaling 117 pages and 40 hours.
- `artifact-manifest.json` binds the source, reviewed digest, 20 DOCX/PDF pairs, and their hashes.
- `qa-report.json` records generator, structural validation, and LibreOffice rendering status.
- `visual-inspection-evidence.json` records flags for each of the 117 PDF pages, per-lesson page counts, source/template hashes, the r6-to-r7 page comparison, and visual image hashes.
- `visual-review/all-pages/` contains page-complete contact sheets; `visual-review/target-pages/` contains larger images of the identified high-risk pages; `visual-review/title-strips.jpg` shows all 20 lesson titles.
- `visual-review/template-comparison/` contains same-input L01, L06, and L18 long-remark comparisons across Templates 1.1.2, 1.1.3, and 1.1.4.

The Template 1.1.4 SHA-256 is `D75A0A777E0BE77525289AAF6464AECDE2783B1E68AE0B9A8BB613F74729DBCD`. The artifact-manifest SHA-256 is `862A198F6CFE87EC8654B459CED62D34D16422EAE15FEE55D859A75C4502C868`; the QA-report SHA-256 is `956F0BC7ECC89FE4E7CC019773E0FA7C86B8AFE9FF9468C4B72DF9C5AEEB1553`; and the page-level visual-evidence SHA-256 is `1CC8A8D11BAD6A7B0612E6384BA298C56C2096703422D1E18245B43A0132B290`.

## Result and limitations

The optional candidate corrects the previously observed L07 p1 clipping, L11 p4 overlap, L14 p4 clipping, narrow evaluation remarks, and sparse reflection-only tails. A second render also corrected missing PDF title text on L03/L04/L09 by mapping the title's East Asian font explicitly. All 117 final PDF pages were covered by visual review. The page matrix compares the original 133-page default run, controlled same-input runs of 1.1.2 and 1.1.3, and the final 1.1.4 candidate; page count alone is not treated as a quality score.

LibreOfficeDev 26.8 rendered the PDFs with a temporary external Fontconfig alias mapping `仿宋` to Noto Sans CJK SC. Microsoft Word/WPS was unavailable, so status remains `WORD_WPS_UNVERIFIED`. The synthetic output does not establish real-course alignment or teacher acceptance. See the [Owner acceptance report](../../../../教案生成器/lesson-plan-docx-generator/docs/evidence/issue-73-synthetic-course/owner-quality-acceptance-report.md) for the comparison matrix and review conclusions.
