# courseware-html-generator

可复用的离线 HTML 课件生成 Skill。它把 Agent 创作的结构化内容渲染为学生课堂展示版和教师逐页备课版，不绑定数据结构或某一门课程。

下游实践课联动：`实践课HTML生成器/practice-class-html-generator` 以本 Skill 的 Courseware Content Contract 1.1 为首选上游输入，并通过稳定的 `slide.id`、`learning_units` 和 `canonical_facts` 关联理论页。课件 Skill 不依赖或反向修改实践课 Skill。

## 目录

```text
courseware-html-generator/
├── agents/openai.yaml
├── docs/content-contract-v1.1.md
├── docs/content-contract-v1.md       # 1.0 历史兼容说明
├── references/courseware-content-gold-benchmark.md
├── examples/
│   ├── data-structures.example.json
│   └── uml.example.json
├── schemas/courseware-content.schema.json
├── scripts/
│   ├── content_contract.py
│   ├── teaching_blueprint.py
│   ├── repair_courseware.py
│   ├── render_courseware.py
│   ├── validate_courseware.py
│   ├── pedagogical_review.py
│   ├── source_truth_validator.py
│   ├── activity_time_reviewer.py
│   ├── install.py
│   └── install_adapters.py
├── tests/
│   ├── test_courseware.py
│   └── browser_smoke.mjs
└── SKILL.md
```

## 数据流

```text
教材 / PPT / 讲义 / 教案
  → Agent Teaching Blueprint
  → Draft Courseware Content Contract 1.1
  → Structural QA → Pedagogical Review
  → 最多两轮自动合同修复 → Revalidation
  → deterministic renderer
  → student.html + teacher.html
  → output/offline/browser QA
  → atomic commit
```

Python 只负责稳定输出，不调用模型、在线 API 或网络资源。输入 JSON 中不能提供任意脚本；代码 block 按文本转义，SVG 仅允许通过安全检查的自包含图形。课程级 `course_context` 可声明语言、工具、平台、软件、数据库方言、框架和其他约束，供下游 Practice Class Skill 继承；Courseware 不反向依赖实践课。

### Source Truth 与时间证据

新生成必须使用 strict evidence mode：先从 Frozen Raw Source 建立可复核的 Source Truth，再把 canonical fact 的 `source_refs`、`evidence` 和 `verification` 带入 Courseware/Practice。当前内置适配器确定性支持 UTF-8 CSV、文本引文和简单 CSV 求和/计数；CSV 明确区分 header row、data row index 与 worksheet row（header 在第 1 行时，data row 2 是 worksheet row 3）。`source_truth_validator.py` 还会建立跨课件、实践任务和教师参考的 fact usage registry，并对单元格地址、数值、日期、公式、代码结果等关键 token 执行一致性检查。

理论课的 `activity_minutes > 0` 必须有 `activity_plan`：包含活动类型、教师提示、学生动作、预期产物、检查方法和分段分钟数；分段总计须与活动时长接近。`activity_time_reviewer.py` 另行检查核心路径与 `session_minutes`、`prepared_minutes` 的关系，以及有真实 `title/minutes/content/activity/use_when` 的 extension reserve。教师 HTML 会显示“课堂活动”和“备用内容 / 讲得快时使用”，学生 HTML 不显示 source id、evidence id、内部验证字段或教师答案。

旧 1.0 或历史 fixture 只可在显式 `migration-trust` 下回归；该模式会保留缺证据事实为 legacy warning，不会把它们自动标为 verified，也不是新生成默认值。

Teaching Blueprint 是公开规划摘要，必须说明目标、时长、对象起点/弱项、learning units、canonical facts、not-yet-taught、教学阶段、视觉/活动需求、误解点和扩展路径；不含 chain-of-thought。页数、脚本段落数和互动数按课程证据决定，不是固定配额。

## 生成

```powershell
python scripts/render_courseware.py `
  --content-json examples/data-structures.example.json `
  --output-dir .\out\data-structures `
  --replace --json
```

生成器默认写入：

- `student.html`
- `teacher.html`
- `qa-report.json`

输出目录必须使用 `--replace` 才能覆盖；生成失败时旧目录保持不变。运行时不需要 Python 依赖，开发时的浏览器测试只需要 Node.js 与 Playwright。

## 合同与 QA

合同字段见 [docs/content-contract-v1.1.md](docs/content-contract-v1.1.md)，旧 1.0 迁移说明见 [docs/content-contract-v1.md](docs/content-contract-v1.md)，机器结构见 [schemas/courseware-content.schema.json](schemas/courseware-content.schema.json)。输出 QA 检查页数/id 对应、页级时间、教学意图、学生禁用词、SVG/图片、安全外链、粗色 `border-left`、单文件离线条件和固定 runtime 标记；教学审查另行检查讲稿容量、重复、视觉说明和核心/扩展路径。

```powershell
python scripts/validate_courseware.py `
  --content-json examples/data-structures.example.json `
  --student-html .\out\data-structures\student.html `
  --teacher-html .\out\data-structures\teacher.html `
  --json
```

严格生成前可单独运行：

```powershell
python scripts/source_truth_validator.py --courseware-json <contract.json> --source-root <frozen-source> --mode strict --output-json <out>/source-truth.json
python scripts/activity_time_reviewer.py --content-json <contract.json> --mode strict --output-json <out>/time-evidence.json
```

## 真实浏览器测试

`tests/browser_smoke.mjs` 使用 Playwright 打开生成的学生 HTML，覆盖背景、标题、卡片、SVG、代码区点击、wheel 上下、单 wheel 不多跳、答案按钮和 `file://` 离线加载。先把 Playwright 安装到任务临时目录，再运行脚本（不把 `node_modules` 放入 Skill）：

```powershell
$nodeDeps = Join-Path $env:TEMP "courseware-playwright"
npm install --prefix $nodeDeps --no-save playwright
$env:COURSEWARE_PLAYWRIGHT_ROOT = Join-Path $nodeDeps "node_modules/playwright"
node tests/browser_smoke.mjs <output>\student.html
```

也可以设置 `COURSEWARE_BROWSER_EXECUTABLE` 指向本机已有 Chrome/Edge，避免下载 Playwright 浏览器。没有 Node.js/Playwright 时，测试应明确失败；这不影响交付 HTML 的零依赖要求。

## 泛化审计

实践课 Skill 的五门 holdout 审计从 Courseware 1.1 合同开始，并与三个已知案例分开作为 regression set。审计会冻结 source packs、分别保存 first-pass/second-pass、运行结构/语义/浏览器 QA，并把 Gold 内容验收保留为人工结论：

```powershell
python ..\..\实践课HTML生成器\practice-class-html-generator\holdouts\build_holdouts.py --freeze-manifest
python ..\..\实践课HTML生成器\practice-class-html-generator\scripts\holdout_audit.py `
  --output-root F:\work\practice-class-generalization-audit-<date> `
  --pass-name first-pass --browser-smoke
```

`Courseware Contract PASS`、`Browser PASS` 和 `Pedagogical Review PASS` 分开记录；它们不等于最终内容授课验收。

## 安装与适配器

```powershell
python scripts/install.py --dry-run
python scripts/install.py --skills-dir "$env:USERPROFILE\.codex\skills"
python scripts/install_adapters.py --target-dir <project>
```

适配器默认只写带 namespaced marker 的规则，支持 Codex/AGENTS、Claude、Gemini、Copilot、Aider、Cursor、Cline、Continue、Windsurf 和 OpenCode。追加 `--copy-engine` 才复制可在目标项目运行的完整 engine；默认不覆盖已有文件。
