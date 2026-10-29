# Content 2.4 practice handoff regression evidence

These reports are generated from explicitly synthetic Content 2.4 fixtures. They are engineering regression evidence, not a real course or a teacher review.

Each fixture was run through the full `content_quality.validate_content_quality` validator. Its `practice_handoff` report was then passed to `lesson_acceptance.practice_handoff_metrics`, matching the Acceptance handoff input path; the same Acceptance metric was also run independently without a supplied QA report. No Word/PDF artifacts were regenerated for this focused validator fix.

| Scenario | Lessons | WorkOrders | Content QA | QA handoff | Acceptance handoff | Independent Acceptance recheck |
| --- | ---: | ---: | --- | --- | --- | --- |
| 40h `separate_full_lessons` (20 theory + 20 practice) | 20 | 10 | passed | passed | passed | PASS |
| 40h `practice_only` | 20 practice | 20 | passed | passed | passed | PASS |

The full machine-readable reports and summary are in `index.json` and the adjacent scenario JSON files. The regression tests also exercise both no-WorkOrder cases, unknown Lesson IDs, duplicate task allocations, overlapping practice-hour allocations, reverse-link mismatches, and unchanged Content 2.2/2.3 behavior.
