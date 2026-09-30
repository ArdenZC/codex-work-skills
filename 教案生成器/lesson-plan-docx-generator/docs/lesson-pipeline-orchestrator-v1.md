# Lesson Pipeline Orchestrator implementation 1.0

独立入口 `scripts/run_lesson_pipeline.py`，复用 Pipeline State Contract 1.0，
停止于 PRODUCTION_AUTHORIZED。本轮没有 final generator、artifact/visual QA 或 ACCEPTED 集成。
Skill 2.3.1、Content 2.2/2.3、Template 1.1.2、Acceptance 2.0 和所有既有 Review/Authorization
合同保持原版本及语义。此路径是 opt-in LIF-04 candidate path。

## 状态与一次一步

| 命令 | 结果状态 | 实际证据 |
| --- | --- | --- |
| init | INTAKE_CONFIRMED | 外部已确认 Source Truth，固定 run ID 与 PREVIEW/PRODUCTION 模式 |
| freeze-source-truth | SOURCE_TRUTH_FROZEN | Manifest 与全部本地 source bytes 复验；PREVIEW 保留远程 bytes 未验证分类 |
| prepare-benchmark | BENCHMARK_PREPARED | Quality Eligibility + quality-only canonical projection + Split/Packs/preparation |
| bind-content | AUTHORING_COMPLETE | 外部 Agent 提供合法 Content 2.2/2.3 |
| validate-preproduction | PREPRODUCTION_QA_PASSED | 原 Content validator 与 content_quality hard gates |
| bind-benchmark-disposition | READY_FOR_TEACHER_REVIEW | 无正式 Review 的 PARTIAL/UNAVAILABLE 或用户 waiver；绑定最终 disposition 与不可变 evidence |
| bind-benchmark-review | BENCHMARK_REVIEW_COMPLETE | 实际完成的 full-linkage Review（包括真实 partial Review）与最终 disposition |
| ready-for-teacher-review | READY_FOR_TEACHER_REVIEW | 从真实 BENCHMARK_REVIEW_COMPLETE 重验上述完整链 |
| prepare-teacher-review | READY_FOR_TEACHER_REVIEW（不变） | 原子发布 deterministic Packet + run binding，不记录 transition |
| bind-teacher-review | TEACHER_REVIEW_APPROVED | 外部 APPROVED / APPROVED_WITH_NOTES Teacher Review；IDs/顺序/reasons 与 Packet exact-match |
| authorize-production | PRODUCTION_AUTHORIZED | 外部合法 Production Authorization 全链、Skill/Template/runtime 复验 |
| status | 不变 | 重新读取所有上游字节与语义，支持独立进程恢复 |

大部分推进命令只执行一个 transition；`prepare-teacher-review` 只冻结 human-review input，
不推进 lifecycle state，不制造 same-state transition。status 同样不推进状态。
不自动完成多个人工步骤、不生成正文、Teacher 评分/notes 或 APPROVED。
REVISION_REQUIRED、缺证据、未知命令或裸状态字符串全部 fail closed。

## 使用

```powershell
python -B scripts/run_lesson_pipeline.py init --run F:\lesson-work\prod-run.json `
  --run-id RUN-001 --mode PRODUCTION --source-truth F:\lesson-work\source-truth.json
python -B scripts/run_lesson_pipeline.py freeze-source-truth --run F:\lesson-work\prod-run.json
python -B scripts/run_lesson_pipeline.py prepare-benchmark --run F:\lesson-work\prod-run.json `
  --source-catalog F:\lesson-work\source.json --quality-eligibility F:\lesson-work\quality.json
python -B scripts/run_lesson_pipeline.py bind-content --run F:\lesson-work\prod-run.json `
  --content F:\lesson-work\content.json
python -B scripts/run_lesson_pipeline.py validate-preproduction --run F:\lesson-work\prod-run.json
```

派生产物写在 `<run-stem>-artifacts/`，QA 写入 `<run-stem>-preproduction-qa.json`。
所有 run 与派生证据必须在独立外部 workspace，不能写 canonical 或提交到仓库。
PREVIEW 和 PRODUCTION 分别建立 run 文件；模式保存在 run envelope 中，不能靠命令覆盖。
PREVIEW 可以准备、绑定外部 Content、QA 和 Review；authorize-production 始终拒绝。
两种模式都执行 `validate_source_truth_file(..., verify_source_bytes=True)`：可验证的本地来源
必须逐字节匹配，HTTPS 来源不联网。PREVIEW 允许结构合法的远程来源，CLI 的
`source_truth_status=STRUCTURALLY_VALID_SOURCE_BYTES_UNVERIFIED` 保留其未验证语义。
PRODUCTION 从 init 到恢复始终要求所有来源 bytes 已验证；远程来源须先冻结为可复验的本地证据。
本轮不调用 diagnostic renderer，也不改变 legacy generator transaction。
迭代创建新 run；旧 run 绑定字节不静默重写。编辑任一源文件、Content、Review 或 sidecar
都会使旧 run STALE，旧 Teacher Review/Production Authorization 不再有效。

## 最终 Benchmark disposition

`bind-benchmark-disposition --disposition <external.json>`（无正式 Review）与
`bind-benchmark-review --disposition <external.json>`（实际 Review）接收外部显式 binding envelope：

```json
{
  "pipeline_run_id": "RUN-001",
  "source_truth_manifest_sha256": "<actual manifest bytes SHA256>",
  "content_sha256": "<actual Content bytes SHA256>",
  "benchmark": {
    "disposition": "BENCHMARK_UNAVAILABLE",
    "authorization_sha256": null,
    "review_sha256": null,
    "evidence_sha256": "<actual external evidence bytes SHA256>",
    "waiver_reference": null
  }
}
```

BENCHMARK_NOT_EXECUTED、benchmark null 和静默 none 均拒绝。非 waiver 必须有真实
quality-gated preparation。准备状态为 PARTIAL/UNAVAILABLE 且尚未执行正式 Review 时，
`--benchmark-evidence <external.json>` 必须包含上述 run/source/content 绑定、
`benchmark_preparation_sha256`、一致的 `disposition` 与非空 `notes`。
READY preparation 不能仅靠文字 downgrade：必须提供实际 full-linkage Review。
无正式 Review 的 PARTIAL/UNAVAILABLE 使用 `bind-benchmark-disposition`，直接从
PREPRODUCTION_QA_PASSED 到 READY_FOR_TEACHER_REVIEW，不记录 BENCHMARK_REVIEW_COMPLETE。
最终 disposition SHA 写入 `state.artifacts.benchmark_disposition_sha256`；该直接 transition 的
正式 evidence 仍为 Pipeline Contract 1.0 的 `preproduction_qa_sha256`。

正式 Review 使用 `--benchmark-review`、`--authoring-selection`、`--holdout-selection`、
`--lesson-reviews-dir`，完成 Review 还需 `--benchmark-authorization`。
Round 2 使用 `--previous-lesson-content`、`--previous-review`、`--previous-lesson-reviews-dir`。
原 `derive_benchmark_authorization_claims` 重验 derived Catalog、Split、两侧 Packs/Selections、
所有 Review shards 与 Content；Authorization 必须匹配重算 claims。
实际 single-context partial 可以显式处置；REVISION_REQUIRED 不允许进入 final authority。
`bind-benchmark-review` 必须提供真实 Review artifact，先进入 BENCHMARK_REVIEW_COMPLETE，
再单独执行 `ready-for-teacher-review`。`bind-benchmark-disposition` 拒绝 Review inputs。
READY 及后续状态明确要求并重新验证 indexed final disposition；history 经过
BENCHMARK_REVIEW_COMPLETE 时还必须存在并重验真实 Review、selections 与 shards。

WAIVED_BY_USER 是唯一允许绕过 preparation 的路径。`bind-content --waiver-evidence` 可绑定
外部用户同意文件；之后最终 disposition 必须重验同一不可变文件。文件至少有 run/source/content
绑定、`decision="WAIVED_BY_USER"`、非空 `user_identity` 和 `waiver_reference`，并与
Benchmark 对象的 evidence SHA/reference 一致。CLI 从不创建此文件或伪造用户 consent。
Waiver 同样使用 `bind-benchmark-disposition` 直接进入 READY，history 不记录 Review Complete；
恢复时继续重验用户同意证据及 disposition。
这些校验证明内容、显式声明与不可变绑定，不声称密码学验证人类身份；调用者负责提供真实用户授权。

## Teacher / Production Authorization

```powershell
python -B scripts/run_lesson_pipeline.py ready-for-teacher-review --run <run.json>
python -B scripts/run_lesson_pipeline.py bind-teacher-review --run <run.json> --teacher-review <external-teacher.json>
python -B scripts/run_lesson_pipeline.py authorize-production --run <run.json> --authorization <external-authorization.json>
python -B scripts/run_lesson_pipeline.py status --run <run.json>
```

上面的 `ready-for-teacher-review` 仅用于已完成真实 Review 的 run；disposition-only run 已直接 READY。

Teacher Review 由外部提供，沿用 Teacher Review 1.0；本轮不实现 deterministic selector。
仅 APPROVED/APPROVED_WITH_NOTES 可推进，必须与当前 Content、Source Truth、run ID 和最终
Benchmark 对象一致。Production transition 与 resume 必须实际调用现有
`validate_production_authorization_files(..., verify_runtime_environment=True)`。

## QA Evidence 1.0 与恢复

QA evidence 绑定 Content 原始字节、实际合同版本、现有 `validate_content_v2_input` PASS、
现有 content_quality 完整报告、课时账、Skill/validator implementation identity、时间和 fingerprint。
报告作为原始序列化 JSON 字符串冻结，保留浮点诊断值；外层仍使用无浮点 lifecycle digest。
resume 重新执行同一 validator 并比较结果，不复制 QA 规则。

Run envelope 包含原 Pipeline State 1.0、模式、implementation version 和全部 artifact paths/
bytes SHA；Review 目录绑定完整文件 inventory。每次重新 replay state history、重读完整证据，
验证 source 内容、Quality/projection、QA、Benchmark、Teacher 以及已授权的 Template/Skill/runtime。
修改 bindings/state/fingerprint 字符串不能替代这些语义校验。
O_EXCL lock 拒绝并发写入；candidate 先验证再原子替换。Preparation/QA 与对应 state 更新
同 bundle 发布，失败恢复旧文件，回滚失败明确报错。

Legacy generator 默认 `--benchmark-mode none` 继续兼容。
直接 generator 的 `production_pass` 表示 artifact transaction 成功，不能等同 lifecycle ACCEPTED。


## Deterministic Teacher Review Packet

```text
READY_FOR_TEACHER_REVIEW
    ↓ prepare-teacher-review（状态不变）
Deterministic Teacher Review Packet 1.0
    ↓ Human Teacher Review（外部 artifact）
bind-teacher-review
    ↓
TEACHER_REVIEW_APPROVED
```

Packet 写入 `<run-stem>-teacher-review-packet.json`，run envelope 的
`bindings.teacher_review_packet` 保存 path + bytes SHA；Pipeline State Contract
1.0 不添加字段。算法与独立校验见
[teacher-review-selection-v1.md](teacher-review-selection-v1.md)。READY 尚无 Packet
可 status；一旦绑定每次 resume 必须重验。Teacher-approved 及以后 Packet mandatory。
绑定 Teacher Review 时，selected lesson IDs、order、selection_reasons 与重新派生的
Packet 必须 exact equality。人工可填评分、备注和判断，不能减少/替换审查样本。
旧 standalone Teacher Review 1.0 合同仍兼容；canonical PRODUCTION 路径拒绝任意手挑样本。
PREVIEW 可准备 Packet / 绑定外部 Review，仍拒绝 Production Authorization。
Content、disposition、Review 或 shard 任意 bytes 改变使旧 run / Packet / Review stale，
须新建 run；禁止静默重新绑定。
