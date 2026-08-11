# Aider 约定

先读取 AGENTS.md、SKILL.md 和 通用提示词.md，再处理教案任务。

- 将用户资料整理为 tasks.json，使用 scripts/generate_lesson_plans.py 生成 DOCX。
- 课程单元按“项目一、项目二……”组织，任务名写成具体动作或成果。
- 默认使用 assets/templates/lesson-plan/v1.1.1/template.docx，保持 30 行主表和原有可见格式；模板版本—定位模式固定为 `1.0.x = legacy_coordinates`、`1.1.x = word_bookmark`，其他 `1.x` minor 拒绝。canonical v1.0.0 模板和旧 assets/lesson-plan-template.docx 仅传模板时自动使用 legacy coordinate mode，自定义模板必须提供匹配 manifest。v1.1.1 保留“突出方法”和“破解方法”固定标签，并将七个课中阶段严格分配为每学时 45 分钟；两学时课中合计 90 分钟，课前和课后不计入课中合计。
- v1.1 语义书签名称必须符合 Word 40 字符安全规则；start/end 必须成对并位于同一 story、同一目标段落或同一物理单元格。
- v1.1 manifest 必须显式声明 anchors、固定字段的 target/bookmark/mode、实施阶段的 id/code/bookmarks、反思书签和评价书签；固定字段的 target/mode/bookmark/container 必须符合集中契约，未知值、版本与 mode 冲突或缺失字段不得静默回退。书签 ID 只接受 ASCII `0-9`。
- v1.1 的固定字段、implementation、reflection、stage 和 evaluation 使用封闭键集合；任何额外的 target、row、cell、bookmark、container 或未知键都必须在模板验证和生成前失败。v1.0 legacy 只允许 canonical 坐标字段和可选 `anchors.mode: legacy_coordinates`，不得夹带 semantic anchors、bookmarks、stages 或混合定位定义。
- 显式 manifest 时，canonical/compatibility 原始模板路径必须与版本精确匹配；自定义模板必须在 manifest 中声明实际文件路径和 SHA-256 fingerprint。普通复制模板不需要修改 ZIP metadata，fingerprint 不匹配是阻断错误。
- 构建器先把生成或复制结果写入临时 DOCX，扫描主文档、所有 header/footer story 和语义物理位置，校验通过后才原子替换目标文件。
- 生成后检查文件数量、总课时、课程名称、评价表和评分总和。
- 资料不足时提醒用户需要的文件，但不要因为缺少资料而停止；按课程特点推断项目化教学结构。
