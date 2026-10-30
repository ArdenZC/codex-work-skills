# Template 1.1.2 / 1.1.3 same-input comparison

## Inputs and outputs

- Final Content Contract 2.4 input SHA-256: `A3927B87BA4EB095D27456A0599DD8C24AA1EA304471A184D7C60A2D735631DB` (same bytes for both runs).
- Default 1.1.2 run: `issue73-quality-acceptance-r4`; template SHA-256: `6FFAFA579D3AACBC535BA624D0A6A766644868B0AF1FCE6AC37B20BA8F3D8FC1`.
- Candidate 1.1.3 run: `issue73-quality-acceptance-r4-v113`; template SHA-256: `D0A5BA37D2CB4AF445F10DE17FBC3363FA26E52C373B3F71EFE0E6C49C47D613`.
- Both runs report `production_pass`, QA `passed`, and LibreOffice render `passed`; the two selected L06 DOCX/PDF pairs are retained in this folder. The remaining candidate run outputs are not retained as comparison artifacts.

| L06 output | Pages | DOCX SHA-256 | PDF SHA-256 |
| --- | ---: | --- | --- |
| Template 1.1.2 | 9 | `AB913EA75192C9B3E2052D34AD416CBEF43A502CA9B2CB04FE0F13F5EB93D747` | `17EAB6D391ACDCDCFA17D4CFD408517087CA4ACC8326FDBBEF9F4F6AF3BB8CF5` |
| Template 1.1.3 | 7 | `FE6F91F14ECEC34D6D480E99382EE7574A6E4643917467C0239FA2D8A9E70E8B` | `0DE10F32F83EE384BEB7FCCA5466A981042B064034B2417FDE15D858DA37374D` |

## Visual finding and migration recommendation

The final-input L06 PDF page 3 was visually compared at full-page scale. Template 1.1.2's narrow remarks column wraps text vertically; 1.1.3 gives the remarks more horizontal room and they read across the row. On this same L06 input, 1.1.3 reduces the output from 9 to 7 pages. This supports a readability improvement for the selected long-remark lesson only; it does not establish full-course superiority.

Keep Template 1.1.2 as the default. A one-Lesson LibreOffice comparison is insufficient to migrate the default, and native Microsoft Word/WPS validation remains unavailable (`WORD_WPS_UNVERIFIED`). Any default migration requires separate Owner approval.
