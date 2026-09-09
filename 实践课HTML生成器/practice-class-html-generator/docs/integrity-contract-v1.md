# Classroom / Reference Integrity Contract 1.0 (Skill 1.2.0)

This additive contract extends Content Contract 1.1. New generation sets root `integrity_version: "1.0"` and uses `--evidence-mode strict --source-root <frozen raw root>`. Old fixtures may explicitly use migration-trust; that mode is regression evidence, never new-generation acceptance. Courseware remains independent of Practice. Read formal docs and Gold principles, not example/holdout contracts, when authoring blind material.

## Authoring sequence

Classify raw classroom files first, plan tasks from taught abilities, then author draft contracts. Validate drafts before rendering. The two-round built-in repair only derives existing links; do not overwrite an emitted package to repair content. Behavior failure prevents teacher pages and final output publication. Keep failures and draft evidence outside student distribution.

## Student assets and project bundles

`starter_assets` retains `id,path,language,task_id,content` and optional editable_gaps. Paths are relative to `student/starter/`. Give every runtime file a real asset entry. Optional `role` is one of student-edit, student-input, runtime-required, generated-scaffold, teacher-reference, test-only. The last two never enter student files or sanitized JSON. Task starter_asset_ids must refer only to student roles.

For any executable project, add root `starter_bundles` array. Each item: `id, artifact_kind:"project", root, entrypoint, files:[{path,role}]`; root is relative to starter/, files and entrypoint relative to the bundle root. Use a directory such as `demo` rather than duplicating `starter/`. For Flask declare `framework:"Flask", template_path:"templates"`. Dynamic template names require `dynamic_template_assets` (paths relative to bundle root). Literal render_template calls are checked against the actual student tree. `runtime_dependencies:[{path}]` extends closure to data, styles, images or other runtime inputs; paths relative to starter/. Include run instructions and framework requirements in the project. Bundle manifests do not create files: every file needs its starter_assets entry.

`classroom_assets` classifies each raw file: `id,title,task_id,source_path,sha256,classification` and, for student inputs, `student_path` relative to starter/. source_path is relative to --source-root. Classifications: source-only-reference, teacher-only-material, student-classroom-input, generated-starter-seed. Student input/seed bytes are copied with matching SHA; no mass raw-source copying. Use the same id/path in an existing starter asset when supplied, or preparation materializes the entry. Asset lineage records the source, decision, target and hash. Classroom data required by a task must be classified and distributed, not merely mentioned in prose.

CSV is an input, not a persistent workbook. For tasks with workbook editing, charting or formatting, provide `spreadsheet_workflow` that explicitly opens the CSV and saves a `.xlsx` working copy before further operations. Put the operational steps in task instructions. A reliable working workbook may also be supplied as a classified binary asset; missing workbook libraries need not block CSV plus explicit workflow.

## Patch model

An editable gap retains `kind,marker,replacement,student_instruction`; `patch_kind` selects replace-expression (legacy default), replace-line, replace-region, replace-block, insert-before, insert-after, add-file. Expression replacements require one unique target/marker. Line insertion and replacement use the whole marker line. Region/block replacements require unique `marker` and `end_marker`, in that order, and replace both markers and enclosed lines. `indent_policy:"inherit"` (default) dedents replacement then applies marker indentation; `explicit` preserves supplied indentation. For add-file use an empty content string and a teacher-only asset role; student tasks may instead edit an existing TODO skeleton. No overlapping or duplicate anchors. Student previews carry only incomplete starters and instructions. All replacement metadata is teacher/QA only.

## Task reference_verification

Every implementation/debugging task or task requiring code_editing/execution needs `reference_verification:{kind:"behavioral", checks:[...]}`. Other tasks declare checks only where suitable. Each check has unique id and verification_type. `required_scenarios:[...]` may require semantic scenario labels on checks. Cover valid, empty and error inputs relevant to the task, including each taught HTTP method. Flask execution requires a complete bundle and multiple request scenarios. Complete implementations assembled from gaps are shown in teacher reference with actual check results; prose is not the authoritative executable version.

Check paths are relative to the completed starter root, not bundle root. Never put checks or answers in student content.

- syntax: Python `path`; contributes syntax evidence only, never behavioral PASS.
- function-call: Python `entrypoint,function,args,kwargs,expected:{equals:...}`.
- web-request: `entrypoint,framework:"Flask",app_object:"app",method,path`, optional query_string/data/json/headers; `expected_status` plus `body_contains:[...]` and/or `expected:{json_equals:...,json_contains:{...}}`. Paths, form fields, parameters and assertions come from the task. Uses test_client, no persistent server.
- command: `argv:[...]`, optional timeout_seconds (bounded), `expected:{returncode,stdout_contains:[...]}`. `{python}` expands to the current interpreter. Shell strings are forbidden.
- file-output: `path,expected:{equals:"exact file text"}`; pair with a preceding command when generation is required.
- query-result: SQLite `setup_file,query,parameters,expected:{rows:[[...]]}`. Other dialects require another adapter or explicit manual evidence; do not pretend SQLite proves another dialect.
- structured-data: JSON `path,expected:{equals:...}`, or `formula_fact` in the formula contract (source_id relative to completed starter root).
- browser/manual-evidence: `procedure,observation,expected_result`. Reports AUTOMATED_UNAVAILABLE and MANUAL_EVIDENCE_DEFINED; never automated PASS. Use this for external tools, models and variable environments. Browser UI smoke is a separate real browser step.

Unknown adapters, missing assertions, timeout, import errors, nonzero execution, wrong results or syntax-only evidence fail closed. Static unreachable/empty-branch findings supplement behavior. A manual check is legal evidence definition, not observed success. Modeling references include model/relationships/results; networking references include reasoning, tool observation and environment boundaries; workbook references include actual fields/formulas/locations/results and acceptable variants.

## Formula truth (shared upstream module)

Root `formula_facts` registers every displayed IF/COUNTIF/SUM/SUMIF/AVERAGE formula. Each item has `id,formula,example_scope`. Abstract examples use `example_scope:"abstract"` and are labeled “语法示例” in student prose. Current examples use `example_scope:"current-dataset"`, `source_id` relative to raw source root, `semantic_intent`, `bindings:{input_field:"exact header"}` or input_fields array, optional field_types mapping, `operation_location`, optional `expected_result`, and Practice `task_id`.

The evaluator derives columns, letters, samples and types from current CSV bytes, compares actual referenced fields with declared intended fields, and computes results. IF literals/comparisons, COUNTIF, SUM, SUMIF, AVERAGE and bounded cell ranges are supported. Formula facts are evaluated in declaration order: writing a result to a single cell makes that derived cell available to later facts on the same source. Declare each current row formula when later aggregates consume it. Unsupported syntax/ranges fail; no guessed Excel semantics. Expected results supplied by the Agent must equal computed results. A text-label COUNTIF over numeric fields fails. Teacher output uses computed results. Binding intent correctness and acceptable variations still require human review.

## Environment and acceptance

Inherit `course_context.delivery_environment` from theory. For computer-lab, default digital recording/tool workspaces. Paper phrases produce COMPUTER_LAB_MODALITY_WARNING unless root paper_work_authorization explains a source/user requirement. Do not force starters onto observational tool tasks.

Gate sequence: Source/Formula Truth → Time Evidence → Contract → pedagogy → project/asset closure and reference behavior → candidate render → student package/link QA → atomic publication → real browser smoke. Any failed behavioral check stops publication. Automatic score must include behavior/package/source-formula/time/browser evidence; manual evidence and unavailable checks are never full objective credit. DEGRADED pedagogy cannot score 30/30. Human stays PENDING /40.
