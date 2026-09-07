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
  → deterministic HTML renderer（四个学生模块 + 两个教师模块，模块内 pane）
  → student/ 学生材料 + teacher/ 教师指导/逐任务参考
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

输出目录严格隔离为：

```text
practice-output/
├─ student/
│  ├─ student-task.html       # 任务路线模块，任务在 pane 内切换
│  ├─ learning-center.html    # 学习中心模块，互动在 pane 内切换
│  ├─ study-guide.html        # 学习指南模块，资料在 pane 内切换
│  ├─ foundation-kit.html     # 基础补给模块，微专题在 pane 内切换
│  └─ starter/                 # 仅在声明 starter_assets 时生成
├─ teacher/
│  ├─ teacher-guide.html       # 课堂指导模块，观察点在 pane 内切换
│  └─ teacher-reference.html   # 教师参考模块，逐任务成果在 pane 内切换
├─ practice-content.json
└─ qa-report.json
```

四个学生模块和两个教师模块都是完整主页面；合同数组映射成各页的 pane，左侧（窄屏时顶部）导航只切换当前 pane，hash 可直接定位一个任务、实验或参考成果。每个 pane 聚焦一个教学对象，正文保持可读的单列宽度，并提供返回目录、上一项、下一项、标题和时间/帮助导航。学生页只在 `student/` 内导航，学生可见文本隐藏合同版本、原始 ID、interaction type 和教师路径；教师页可以反向链接学生页。`course_context` 从上游 Courseware Contract 继承语言、工具、平台、软件、数据库方言等强约束。离线输出是可导航的站点包，不是把内容拆成大量详情 HTML，也不是单一 HTML 文件。

## 合同与验证

合同说明见 [docs/content-contract-v1.md](docs/content-contract-v1.md)，机器结构见 [schemas/practice-class-content.schema.json](schemas/practice-class-content.schema.json)。

```powershell
python scripts/validate_practice.py `
  --practice-json examples/data-structures.practice.json `
  --courseware-json ..\..\HTML课件生成器\courseware-html-generator\examples\data-structures.example.json `
  --output-dir .\out\data-structures --json
```

验证会检查合同结构、按时长给出的 Gold 内容密度建议、知识点与任务自身的 `source_slide_ids`、core 关联、任务层级、上下文继承、真实 starter 空位、学习中心关联、renderer family、终止状态、学生可见文本、六个模块页的 pane/hash 内部链接、学生/教师目录隔离、draw.io starter 和逐任务教师参考；浏览器 smoke 检查全部六个主页面、多桌面宽度、真实互动及无横向溢出，但不会替代教师对教学内容的审阅。参考抽象规则见 [references/content-quality-gold-benchmark.md](references/content-quality-gold-benchmark.md)。**自动化 PASS 不代表内容验收通过，等待真实 HTML 内容验收。**

## 三套内容形态

- 数据结构：C 语言二分查找区间模拟、边界诊断和可编译 starter；
- 软件建模/UML：从用例目标走向领域对象和时序责任，使用可编辑 draw.io XML，不带 C/代码模板；
- 数据库：MySQL ER 映射、JOIN 路径、SQL 结果预测、子句诊断和约束工具操作。

## 浏览器 smoke

```powershell
$nodeDeps = Join-Path $env:TEMP "practice-class-playwright"
npm install --prefix $nodeDeps --no-save playwright
$env:PRACTICE_PLAYWRIGHT_ROOT = Join-Path $nodeDeps "node_modules/playwright"
$env:PRACTICE_BROWSER_EXECUTABLE = "C:\Program Files\Google\Chrome\Application\chrome.exe"
node tests/browser_smoke.mjs .\out\data-structures
```

smoke 会从 `file://` 打开每套输出的四个学生模块和两个教师模块，在 1366×768、1440×900、1920×1080 检查无横向溢出和无外部请求，逐 pane 切换，并实际点击选择、步骤、分类、排序、状态模拟、连续诊断、多参数比较和多题互动；教师参考页还会检查模型 SVG 的计算样式与可见尺寸，内部链接由 `validate_practice.py` 同时检查。Chrome/Edge 可通过 `PRACTICE_BROWSER_EXECUTABLE` 指定已有可执行文件。这里的自动化 PASS 只说明结构与交互可运行，不替代 Gold Sample 并排内容验收。
