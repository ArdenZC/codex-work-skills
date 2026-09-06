# practice-class-html-generator

通用实践课 HTML 生成 Skill。核心不是把任务写得漂亮，而是让学生能依据已经讲过的理论完成一个可观察结果，并在遇到卡点时知道去哪里自助。

## 目录

```text
practice-class-html-generator/
├── agents/openai.yaml
├── docs/content-contract-v1.md
├── examples/
│   ├── data-structures.practice.json
│   ├── uml.practice.json
│   ├── database.practice.json
│   └── database-courseware.example.json
├── schemas/practice-class-content.schema.json
├── scripts/
│   ├── practice_contract.py
│   ├── render_practice.py
│   ├── validate_practice.py
│   ├── install.py
│   └── install_adapters.py
├── tests/test_practice_class.py
├── tests/browser_smoke.mjs
└── SKILL.md
```

## 数据流

```text
Courseware Content Contract 1.0 / 课程资料
  → Agent 创作 Practice Class Content Contract 1.0
  → 理论关联与学生可完成性 QA
  → deterministic HTML renderer
  → 任务书 / 学习中心 / 学习资料 / foundation kit / 教师指导
  → file:// 浏览器 smoke
```

## 生成

```powershell
python scripts/render_practice.py `
  --practice-json examples/data-structures.practice.json `
  --courseware-json ..\..\HTML课件生成器\courseware-html-generator\examples\data-structures.example.json `
  --output-dir .\out\data-structures --replace --json
```

不提供 `--courseware-json` 时，只能使用 `source_courseware.mode = independent` 的合同；联动合同会在缺少上游文件时失败。生成不需要 Python 第三方依赖。

输出目录包含 `student-task.html`、`learning-center.html`、`study-guide.html`、`foundation-kit.html`、`teacher-guide.html`、`practice-content.json`、`qa-report.json` 和可选 `starter/`。

## 合同与验证

合同说明见 [docs/content-contract-v1.md](docs/content-contract-v1.md)，机器结构见 [schemas/practice-class-content.schema.json](schemas/practice-class-content.schema.json)。

```powershell
python scripts/validate_practice.py `
  --practice-json examples/data-structures.practice.json `
  --courseware-json ..\..\HTML课件生成器\courseware-html-generator\examples\data-structures.example.json `
  --output-dir .\out\data-structures --json
```

验证会检查 source slide、core 关联、任务层级、学习中心关联、HTML 内部链接和五份输出，但不会替代教师对教学内容的审阅。

## 三套内容形态

- 数据结构：二分查找区间追踪，Python starter 只留 5 个关键 TODO；
- 软件建模/UML：从用例目标走向领域对象和时序责任，使用建模工具脚手架，不带编程模板；
- 数据库：ER 映射、主外键和 SQL 结果预测，配合 Workbench 操作起点。

## 浏览器 smoke

```powershell
$nodeDeps = Join-Path $env:TEMP "practice-class-playwright"
npm install --prefix $nodeDeps --no-save playwright
$env:PRACTICE_PLAYWRIGHT_ROOT = Join-Path $nodeDeps "node_modules/playwright"
node tests/browser_smoke.mjs .\out\data-structures
```

smoke 会从 `file://` 打开五份页面，检查选择/步骤互动和无外部请求；内部链接由 `validate_practice.py` 同时检查。Chrome/Edge 可通过 `PRACTICE_BROWSER_EXECUTABLE` 指定已有可执行文件。
