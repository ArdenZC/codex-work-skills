# Holdout Evaluation Boundary

本文件保留历史架构回归的 provenance，但不再把既有 fixture 的分数叫作
generalization teaching-quality score。

## Architecture Diversity Test

旧输入位于 `实践课HTML生成器/practice-class-html-generator/holdouts/source-packs/`
和 `practice-contracts/`，由 `build_holdouts.py` 生成。它们提前设计了 learning
units、任务数量、层级、互动和参考资料，只能证明 Contract、renderer、validator、
capability/scaffold、visualization adapter 与 package isolation 的兼容性。历史
`93.8` 保留为 architecture compliance score / structured contract diversity score，
不代表 Skill 从陌生资料完成了教学设计。

## Blind Teaching Generalization Test

Blind 输入位于同目录的 `holdouts/blind/`，首轮只提供三套冻结 raw source：H1
Python Web、H2 Excel/数据处理、H3 计算机网络。任务、学习单元、互动、学习指南、
foundation kit、脚手架与教师参考必须由独立 Agent 根据正式 Skill 自主产生。首轮
输出放在 `F:\work\blind-generalization-20260907\`，由
`BLIND-GENERALIZATION-EVALUATION.md` 记录；Human Gold Review 完成前不得写
`GENERALIZATION PASS`，也不得自动填满 40 分。

本轮冻结 revision、生成方法、客观 QA、pedagogical review、模板化警报和人工审核
状态均必须与真实 HTML 一起保存。Second-pass 只有人工审核后、且在 Skill/通用规则
层面完成改动时才允许开始；本轮 First-pass 完成后立即停止。
