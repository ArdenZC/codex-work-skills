# Blind First-pass Generation Instructions

本文件是三次独立 Agent 生成的统一操作说明。它只允许 Agent 读取：

- `HTML课件生成器/courseware-html-generator/SKILL.md`、`简介.md`、`通用提示词.md`、`AGENTS.md`、Contract 文档和 Gold Benchmark 原则；
- `实践课HTML生成器/practice-class-html-generator/SKILL.md`、`简介.md`、`通用提示词.md`、`AGENTS.md`、Contract 文档和 Gold Benchmark 原则；
- 指定课程的 `实践课HTML生成器/practice-class-html-generator/holdouts/blind/<course>/` raw source pack；
- 通用 renderer、validator 和浏览器 smoke 脚本。

禁止读取或复制以下历史案例/答案：

- `HTML课件生成器/courseware-html-generator/examples/data-structures*`、`examples/uml*`；
- `实践课HTML生成器/practice-class-html-generator/examples/*`；
- `实践课HTML生成器/practice-class-html-generator/holdouts/source-packs/*`；
- `实践课HTML生成器/practice-class-html-generator/holdouts/practice-contracts/*`；
- `holdouts/build_holdouts.py`、Gold Sample HTML 正文和任何既有 holdout 生成答案。

每次独立生成必须先从 raw source 自主规划 Courseware Contract 1.1，再从生成出的
Courseware Contract 1.1 自主规划 Practice Contract 1.1。不得人工预设 task 数量、
层级、interaction 类型、learning-center 数量、study-guide 目录、foundation kit
目录或 teacher reference 结构；不得直接写 HTML；不得为通过结构门禁而复制讲稿。

Agent 将合同和可公开的设计摘要写入任务专用 input 目录，然后调用：

```powershell
python tools/blind_generalization/run_blind_holdout.py `
  --source-pack <frozen raw source pack> `
  --courseware-skill <courseware-html-generator directory> `
  --practice-skill <practice-class-html-generator directory> `
  --courseware-json <agent-created Courseware Contract 1.1> `
  --practice-json <agent-created Practice Contract 1.1> `
  --generation-decision <agent-created decision summary> `
  --generation-method agent-skill `
  --output <first-pass course output> `
  --browser-smoke
```

Runner 会验证 source freeze、运行 renderer/validator/browser smoke、复制合同和
raw source、记录命令证据，并在生成尝试结束后冻结输出。First-pass 目录一旦生成，
不得覆盖或修补；问题只能留在报告中，等待人工审核后决定是否启动 second-pass。
