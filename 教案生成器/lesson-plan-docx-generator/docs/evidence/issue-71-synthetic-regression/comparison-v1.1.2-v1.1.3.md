# Issue #71 — Option B visual comparison

This evidence compares the same committed synthetic input under the unchanged Template 1.1.2 and the new Template 1.1.3. The source JSON SHA-256 is identical for both runs. It is a synthetic regression, not a reproduction of the unavailable user DOCX or the 20-file course package.

## Versions and outputs

| Item | Template 1.1.2 baseline | Template 1.1.3 Option B |
| --- | --- | --- |
| Template SHA-256 | `6ffafa579d3aacbc535ba624d0a6a766644868b0af1fce6ac37b20ba8f3d8fc1` | `d0a5ba37d2cb4af445f10de17fbc3363fa26e52c373b3f71efe0e6c49c47d613` |
| Manifest SHA-256 | `31a9a13783e6233235cc80a84e0d111a82f667f1e49a1019c9afe8eefc8e5af9` | `dc1f9943ea5a863c2d349b169fb6f46ebfba159ff3e0f70d086a438606b2f275` |
| Evaluation widths (twips) | `[2088, 3402, 1275, 993]` | `[1304, 2948, 737, 2769]` |
| Evaluation widths (cm) | `[3.68, 6.0, 2.25, 1.75]` | `[2.3, 5.2, 1.3, 4.88]` |
| Generated DOCX SHA-256 | `7f60cfff681d3e212eb8bd01518bdb4408b938057565ad26e412abded1f8dee8` | `112701905764cfab3b218cb35c56028398fcebe2d9357c9116b9aa06ccae8ecb` |
| Rendered PDF SHA-256 | `4a39c4599c6dffc3f28a98b99aa4e073f77e28058bb8a37eb335b7efd17c4b36` | `9287ba7c527b7beb03b99c49083517140fbec6ef03cbd34ca309152b2b07390d` |
| PDF pages | 7 | 5 |

- Input: [`synthetic-lesson-content.json`](synthetic-lesson-content.json), SHA-256 `fd9131e1e74138bd02fb0065d77ba1334daf8f5cdc615067f25cb105dc29404a`.
- Renderer: LibreOfficeDev 26.8.0.0.alpha0 2c87e51eeaa2b413ff4ae097b2705eea1995d8e5. The retained PDFs and PNG page captures are generated from this renderer; Microsoft Word and WPS were not used.
- Both generation runs reported production pass, QA passed, and LibreOffice render passed.

## Visual review

The baseline evaluation table spans pages 2–4. Its 1.75 cm remarks column wraps Chinese text nearly character by character; page 3 and page 4 begin with remark continuations. Page 7 contains only the end of the teaching reflection, followed by a large blank area.

The v1.1.3 evaluation table spans pages 2–3. The remarks column is 4.88 cm wide and displays remarks in ordinary horizontal lines. The longest criterion, “行为习惯、环境维护（5）”, is fully visible; scores and remarks are not clipped. Each rubric row is kept together, so page 3 begins with the complete “课中讨论、答题等（10）” evaluation row and its full remark. The nested table header is not repeated on page 3, so read the two evaluation pages in sequence.

Page 5 includes the remaining teaching implementation content and all three reflection entries. There is whitespace below the final table, but no extra blank page; the template footer is blank in both renders.

Page captures: [`rendered-pages/`](rendered-pages/). Open the retained PDFs for full-size review.

## Content and integrity checks

- All 14 × 4 evaluation cells compare exactly between the generated DOCX files, including 13 scores and all 13 remarks; merged-cell topology and bookmark signatures also compare exactly.
- Both outputs report 70 required and 70 preserved semantic anchors. Template validation reports 14 rows × 4 columns and a constant 7,758-twip evaluation table width.
- The committed Issue #71 synthetic input has score total `88.5` and a `21.5` score in the 25-point rubric row; it does not contain `23.5`. A separate transient regression case changes a temporary copy to total 90.5 and verifies the 23.5 cell under v1.1.3. The committed input and its provenance were not changed.
- Existing Template 1.1.2 remains unchanged: template SHA-256 `6ffafa579d3aacbc535ba624d0a6a766644868b0af1fce6ac37b20ba8f3d8fc1` and manifest SHA-256 `31a9a13783e6233235cc80a84e0d111a82f667f1e49a1019c9afe8eefc8e5af9`.

## Scope limits

The user’s original DOCX and the other 19 course files were absent from the workspace, so original-file and batch claims remain pending. The manual visual qualification covers only this synthetic document in LibreOffice 26.8.
