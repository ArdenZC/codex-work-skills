---
name: courseware-html-generator
description: 根据教材、PPT、讲义、教案或课程资料生成离线单文件 HTML 学生展示版和教师逐字稿备课版；适用于需要稳定课堂交互、SVG/代码/表格/练习和逐页讲稿的高职或大专理论课程。
metadata:
  short-description: 生成离线学生展示版与教师逐字稿版 HTML 课件
---

# HTML 课件生成器

## 目标与边界

使用本 Skill 时，Agent 负责读取用户资料、理解课程主题、规划页面和创作完整的 `Courseware Content Contract 1.0` JSON。内置 Python 脚本负责确定性校验、布局、CSS/JavaScript、单文件输出和 QA；不要让模型直接拼接最终 HTML，也不要在输入中提交任意 JavaScript。

本 Skill 仍独立于教案 DOCX 和旧实践任务工单 Skill：不要解析或修改它们的输出，也不依赖 `practice-class-html-generator`。新的实践课 Skill 可以直接消费本 Skill 产出的 Courseware Content Contract 1.0；因此必须保持 `slide.id` 稳定，并且 Courseware 不反向依赖实践课 Skill，也不绑定到某个课程主题。

## 使用流程

1. 阅读当前会话、附件和本 Skill 的 `通用提示词.md`。从资料提取课程事实；未知事实不得伪造。
2. 先规划整章的页面顺序，再逐页创作学生内容和可以直接在讲台上朗读的 `speaker_script`。每页保留一个稳定的 `id`。
3. 将内容写成 `schemas/courseware-content.schema.json` 描述的 JSON。至少提供课程标题、章节标题、授课对象、内部内容储备字段、主题和 `slides`；若课程有明确语言、工具、平台、软件、方言或框架，写入 `course_context`，供下游实践课准确继承。
4. 每页提供标题、布局、blocks、逐字稿和建议分钟数。block 只能使用合同声明的 paragraph、bullets、cards、table、code、formula、svg、quiz、stepper、comparison、summary 类型。
5. 用 `scripts/render_courseware.py` 生成 `student.html`、`teacher.html` 和 QA 报告；生成器会先在 candidate 目录中完成合同、内容、离线和输出 QA，再原子替换正式目录。
6. 运行 `scripts/validate_courseware.py` 或包内测试。交付前必须真实打开生成的 HTML，验证任意非交互区域点击翻页、滚轮上下翻页和交互按钮不误翻页。

## 内容要求

- 默认面向高职/大专学生；保持课程需要的理论深度，不自动写成考研教材。
- 学生页要像成熟课堂 PPT：明亮冷白/浅灰蓝底色、深色正文、高信息密度、完整细边框卡片、双栏/表格/对比/图示合理组合。禁止深色背景和 `border-left: 4px solid ...` 粗色强调条。
- 学生页不得出现制作信息、教师备注、来源式措辞或内部控时信息，包括“120分钟”“备课版”“学生版”“教师版”“最大可用”“本页建议”“教师提示”“原PPT”“上传资料”“高职学生”等；`content_reserve_minutes` 和 `suggested_minutes` 只用于内部 QA 和教师版。
- SVG 必须是自包含教学图，承担树、图、UML、流程、架构、状态、数据变化或对比等教学信息；不得依赖外部字体、图片、网络资源或跨 SVG 的 id。renderer 会给合法 id 加稳定命名空间。
- 教师版必须与学生版逐页对应。逐字稿是连续自然中文口语，必须包含进入本页、讲解、例子、对图/代码/表格的说明、自然提问、可能回答后的接话、易错点和到下一页的过渡；不能用“讲一下定义”“追问学生”“控时7分钟”这类提纲代替正文。
- `suggested_minutes` 只是教师版页首和逐字稿长度 QA 的内部字段，绝不渲染到学生页。逐字稿需要达到页时长的合理最低容量，不能用底部提示框凑时长。
- 练习支持判断、单选、看图回答、小计算和代码预测；答案默认隐藏，按钮必须阻止全局翻页。stepper/过程动画要可重置、能上一步/下一步、停在最终状态，静态显示时也能理解。

## 运行时要求

renderer 内置并固定以下行为，不能仅写在提示词里：

- 学生版在任意非交互区域的真实单击（背景、标题、文字、卡片、表格普通区域、SVG、代码区域）进入下一页；拖拽选择文字不翻页；button、a、input、textarea、select、`[role=button]` 等控件不触发翻页。
- 鼠标滚轮向下/向上翻页；使用非被动监听、deltaMode 归一化、累积阈值和冷却，防止一次触控板手势连续跳页；`file://` 直接打开也工作。
- `←/→`、`PageUp/PageDown`、Space、Home/End 可翻页。
- 学生版提供小型“投影增强”按钮，只提高正文、次级文字、SVG 和卡片边框对比度，不改变布局。
- 页面中只使用 renderer 固定的内联 CSS/JavaScript。输入中的代码按文本转义，SVG 经过安全检查；不得执行输入 JSON 中的脚本。

## QA 门禁

生成失败时不要覆盖已有正式目录。必须检查：

- 合同字段、block 类型和必要字段合法；学生/教师页数相同，page id 一一对应；教师每页有逐字稿且长度达到建议分钟数阈值。
- 学生输出没有禁用词、分钟/来源/制作措辞；无粗色 `border-left`；SVG 成对闭合且无脚本、事件属性、外部引用；没有外部 stylesheet、script、字体、图片或 CDN。
- 两份输出都是单文件 HTML，资源全部内联，学生页只含学生可见内容，教师页左栏复用同一学生页内容并显示教师右栏。
- 至少执行一组真实浏览器交互测试：点击背景、标题、普通卡片、SVG、代码区，滚轮上下，一次 wheel 不多跳页，交互按钮不额外翻页，以及本地 `file://` 加载。

## 命令

```powershell
python scripts/render_courseware.py `
  --content-json examples/data-structures.example.json `
  --output-dir .\out\courseware `
  --replace --json

python scripts/validate_courseware.py `
  --content-json examples/data-structures.example.json `
  --student-html .\out\courseware\student.html `
  --teacher-html .\out\courseware\teacher.html `
  --json
```

输出目录包含 `student.html`、`teacher.html` 和 `qa-report.json`。它们可以直接复制到用户指定目录；测试过程中的临时目录、浏览器 profile 和日志应在验证后删除。

## 多 Agent 适配

默认安装到 Codex skills 目录只复制 Skill 本身。需要将规则写入其他项目时，运行：

```powershell
python scripts/install_adapters.py --target-dir <project>
```

它支持 Codex/AGENTS、Claude、Gemini、Copilot、Aider、Cursor、Cline、Continue、Windsurf 和 OpenCode 的 namespaced 规则；默认不覆盖目标项目已有内容，只有 `--replace` 才替换。需要在目标项目直接运行完整 engine 时显式追加 `--copy-engine`。
