# courseware-html-generator

可复用的离线 HTML 课件生成 Skill。它把 Agent 创作的结构化内容渲染为学生课堂展示版和教师逐页备课版，不绑定数据结构或某一门课程。

下游实践课联动：`实践课HTML生成器/practice-class-html-generator` 以本 Skill 的 Courseware Content Contract 1.0 为首选上游输入，并通过稳定的 `slide.id` 关联理论页。课件 Skill 不依赖或反向修改实践课 Skill。

## 目录

```text
courseware-html-generator/
├── agents/openai.yaml
├── docs/content-contract-v1.md
├── examples/
│   ├── data-structures.example.json
│   └── uml.example.json
├── schemas/courseware-content.schema.json
├── scripts/
│   ├── content_contract.py
│   ├── render_courseware.py
│   ├── validate_courseware.py
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
  → Agent 规划与创作 Courseware Content Contract 1.0
  → Contract QA
  → deterministic renderer
  → student.html + teacher.html
  → output/offline/browser QA
  → atomic commit
```

Python 只负责稳定输出，不调用模型、在线 API 或网络资源。输入 JSON 中不能提供任意脚本；代码 block 按文本转义，SVG 仅允许通过安全检查的自包含图形。

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

合同字段见 [docs/content-contract-v1.md](docs/content-contract-v1.md)，机器结构见 [schemas/courseware-content.schema.json](schemas/courseware-content.schema.json)。输出 QA 检查页数/id 对应、逐字稿长度、学生禁用词、SVG、安全外链、粗色 `border-left`、单文件离线条件和固定 runtime 标记。

```powershell
python scripts/validate_courseware.py `
  --content-json examples/data-structures.example.json `
  --student-html .\out\data-structures\student.html `
  --teacher-html .\out\data-structures\teacher.html `
  --json
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

## 安装与适配器

```powershell
python scripts/install.py --dry-run
python scripts/install.py --skills-dir "$env:USERPROFILE\.codex\skills"
python scripts/install_adapters.py --target-dir <project>
```

适配器默认只写带 namespaced marker 的规则，支持 Codex/AGENTS、Claude、Gemini、Copilot、Aider、Cursor、Cline、Continue、Windsurf 和 OpenCode。追加 `--copy-engine` 才复制可在目标项目运行的完整 engine；默认不覆盖已有文件。
