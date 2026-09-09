# 文档索引

这里是 `codex-work-skills` 的维护与验收文档入口。普通使用者通常只需要阅读根目录 [README](../README.md) 和目标 Skill 的 `SKILL.md`；本目录主要用于维护、发布、验收和工程追踪。

## 使用与验收

- [Lesson Acceptance](lesson-acceptance.md) — 教案生成结果的本地验收、报告和人工复核协议。
- [Lesson Acceptance Report Schema](lesson-acceptance-report.schema.json) — 验收报告结构定义。
- [Test Execution](test-execution.md) — 仓库测试执行方式和分层说明。

## 模板包

- [Template Package Standard](template-package-standard.md) — canonical template package 的目录、manifest、fingerprint 和兼容性规范。
- [Template Package Authoring](template-package-authoring.md) — 新模板包制作与校验流程。
- [Template Package Release](template-package-release.md) — 版本、archive、GitHub Release 与 installed state 的发布边界。

## Skill 入口

| Skill | Canonical contract |
| --- | --- |
| 教案生成器 | [SKILL.md](../教案生成器/lesson-plan-docx-generator/SKILL.md) |
| 实践任务工单生成器 | [SKILL.md](../实践任务工单生成器/practice-task-workorder-generator/SKILL.md) |
| HTML 课件生成器 | [SKILL.md](../HTML课件生成器/courseware-html-generator/SKILL.md) |
| 实践课 HTML 生成器 | [SKILL.md](../实践课HTML生成器/practice-class-html-generator/SKILL.md) |
| 平时成绩记分册生成器 | [SKILL.md](../平时成绩记分册生成器/course-gradebook-generator/SKILL.md) |

## 仓库级规则

- [AGENTS.md](../AGENTS.md) — Codex / 通用 Agent 规则。
- [CLAUDE.md](../CLAUDE.md) — Claude Code 入口。
- [GEMINI.md](../GEMINI.md) — Gemini CLI 入口。
- [CHANGELOG.md](../CHANGELOG.md) — 面向使用者的重要版本变化。

## 工程验收与阶段性证据

根目录保留以下阶段性文档，主要用于追踪 generalization、holdout 和 release 过程，不是普通用户的必读材料：

- [GENERALIZATION-ARCHITECTURE-REPORT.md](../GENERALIZATION-ARCHITECTURE-REPORT.md)
- [GENERALIZATION-QA-REPORT.md](../GENERALIZATION-QA-REPORT.md)
- [HOLDOUT-EVALUATION.md](../HOLDOUT-EVALUATION.md)
- [DUAL-TEACHING-SKILLS-RELEASE-NOTES.md](../DUAL-TEACHING-SKILLS-RELEASE-NOTES.md)
- [DUAL-TEACHING-SKILLS-RELEASE-MANIFEST.json](../DUAL-TEACHING-SKILLS-RELEASE-MANIFEST.json)

## 版本阅读原则

本仓库刻意把以下版本分开：

```text
Skill version
Content Contract version
Template version
Release archive version
Installed runtime fingerprint
```

它们不是同一个概念。判断当前 Skill 能力时，以对应 Skill 的 `manifest.yaml` / `SKILL.md` 为准；判断模板包时，以 canonical template manifest 为准；判断实际安装状态时，以 installer / doctor 的 fingerprint 结果为准。
