# Quality-Gated Benchmark Preparation 1.0

这是 Lesson Skill 2.3.1 的 opt-in LIF-03 candidate foundation，不是 Skill 2.4 stable。
所有操作离线：不搜索来源、下载、调用 provider 或判断 exemplar 教学质量。
Quality Eligibility 1.0 必须由外部判断者提供，先对**完整原始 Catalog**校验。

## Projection 与稳定分组

Derived Catalog 仍是 Catalog Contract 1.0，课程上下文与 source 完全相同。
只复制 QUALITY_ELIGIBLE 组中的全部结构 QUALIFIED Cards，原始 Card 语义不变；
CONDITIONAL、REJECTED、DISCOVERY_ONLY Cards 即使在同组也排除。禁止 cherry-pick。
`quality-catalog-<digest>` 的 digest 绑定 source Catalog fingerprint 与 Eligibility
fingerprint，derived identity 与 source identity 必须不同。

Derived Catalog 交给原有 `build_split` / `validate_split_payload` 和
`build_exemplar_pack` / `validate_pack_payload`。Preparation 同时重算完整 Catalog 的
Split，确认每个保留组的侧别不变。禁止重平衡、复制组或修改稳定 assignment policy。
下游 Selection、Review 与 Benchmark Authorization 使用 derived Catalog 及同一 Split/Packs，
不改变其合同或 15 维 rubric。完整原始 Catalog 不交给 Author/Reviewer。

## Availability 与 disposition

每侧 0 组为 UNAVAILABLE、1 组为 PARTIAL、2+ 组为 AVAILABLE。
`benchmark_quality_availability` 沿用原策略，跟随 B；`BENCHMARK_READY` 还要求
A 和 B **都 AVAILABLE**。B 为 UNAVAILABLE 时 preparation 为 BENCHMARK_UNAVAILABLE；
其余尚不 READY 时为 BENCHMARK_PARTIAL。两组可能全在一侧，不能伪报 READY。
0 个 eligible group 是合法 UNAVAILABLE，1 组不能复制到两侧。

Preparation 的 READY 是数据准备状态，不等于最终 BENCHMARK_REVIEW_COMPLETE。
最终 disposition 仍为 Lifecycle 1.0 的 REVIEW_COMPLETE / PARTIAL / UNAVAILABLE /
WAIVED_BY_USER。PARTIAL/UNAVAILABLE 需要显式证据与外部 Teacher Review；它们不自动判整课失败。

## `benchmark-preparation.json`

Schema 位于 `schemas/benchmark-preparation.schema.json`。记录 version、pipeline run、
source/quality/derived identity 与 fingerprints、每个文件的 SHA、Split/Packs、eligible groups、
两侧 availability、preparation disposition、时间和 preparation fingerprint。
额外保存 source Catalog 的原始文件 SHA，空白字节变化也会 stale。
Fingerprint 使用现有 lifecycle digest；时间与自身 fingerprint 排除，组 ID 视为无序集合。

验证必须同时重新读取 source Catalog、Eligibility、derived Catalog、Split、A/B Packs，
调用既有 schema/语义 validator，重建 canonical projection、复算 assignment 和实际字节哈希。
裸 fingerprint、旧 source 或篡改 Card/Split/Pack 不能证明有效。

独立 CLI：

```powershell
python -B scripts/benchmark_preparation.py prepare --run-id RUN-001 `
  --source-catalog <source.json> --quality-eligibility <quality.json> `
  --projected-catalog <derived.json> --split <split.json> `
  --authoring-pack <a.json> --holdout-pack <b.json> `
  --preparation <benchmark-preparation.json>
```

`validate` 使用相同六个 artifact 参数，无须 `--run-id`。
所有派生产物位于独立外部 workspace。五文件 bundle 复用 Split 的 candidate/fsync/
atomic-replace/失败恢复 transaction；不会把部分准备结果报告为通过。
