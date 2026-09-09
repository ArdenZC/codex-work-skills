# HTML 课件生成器 Agent 规则

先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`，再决定输入与生成方式。

## Agent 与 Python 的边界

- Agent 读取教材、PPT、讲义、教案和会话资料，规划页面顺序，创作学生页正文和教师自然中文逐字稿。
- 正式输入是 `Courseware Content Contract 1.1` JSON；兼容读取 1.0 时只能通过内置迁移进入 1.1，不能把旧字段继续当作生产格式。不要让模型直接写最终 HTML、CSS 或 JavaScript，也不要在 JSON 中提供任意脚本。
- Python 只做合同验证、有限安全清理/命名空间、固定视觉系统、布局、交互 runtime、输出 QA 和原子提交；不会替缺失资料编造事实。

## 自适应流程

- 先从 Raw Source 建立公开 Teaching Blueprint，再创作 Draft Contract；蓝图必须覆盖目标、时长、对象起点/弱项、learning units、canonical facts、not-yet-taught、教学阶段、视觉/活动需求、误解点和 prepared extension plan，不得写 chain-of-thought。
- 依次执行 Structural Validation、Pedagogical Review、最多两轮 Automatic Contract Repair、Revalidation、Render 和 Browser QA。修复器只能补同一合同可推导的链接/字段，不能编造事实、扩展页或讲稿。
- `prepared_minutes > session_minutes` 时，必须让核心路径和 extension `delivery_track` 可被教师识别；页数、互动数和讲稿段落数不是质量配额。

## 内容质量

- 默认授课对象是高职/大专学生；内容应跨课程可用，至少自然支持数据结构/算法、C/Java/Python、数据库/SQL、UML/软件建模和人工智能基础等理论课程。
- 学生页保持明亮莫兰迪学院风、16:9 投影布局和较高课堂信息密度；禁止深色背景、粗色左边条和装饰性动画。
- 学生页不显示任何制作、来源、教师或控时信息；1.1 的根级/页级时长和讲稿辅助字段只能用于 QA/教师版。旧 `content_reserve_minutes` 只在迁移时读取，不能出现在新合同。
- 每个教学 SVG 必须自包含并承担教学信息；每个练习答案默认隐藏；交互控件不得触发全局翻页。讲稿低于约 80 字/讲解分钟由教学审查判为失败，约 120–160 字/分钟是正常目标，不是 schema 硬错误。
- 教师逐字稿要能直接朗读，不能用提示词、短提纲或底部框冒充连续讲解；正文长度要与页建议分钟数匹配。

## 交互和离线门禁

- 学生版任意非交互区域点击下一页，包含文本、卡片、表格、SVG、代码和背景；拖拽选择文字不翻页。
- wheel 使用 deltaMode、累积阈值和冷却稳定翻页；键盘支持箭头、PageUp/PageDown、Space、Home/End。
- HTML 必须是 Chrome/Edge 可从 `file://` 双击打开的单文件，不使用 CDN、外链图片、外部字体、服务器或 npm runtime。
- 交付前必须真实浏览器验证点击与滚轮，并运行合同/输出/离线 QA；不要把源码字符串断言当成浏览器验收。

## 输出边界

生成器走 candidate → QA → atomic commit；任一失败都保持正式输出目录原状。独立于教案 DOCX 和实践任务工单，不修改其他 Skill 的模板、合同或输出。
