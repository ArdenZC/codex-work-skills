"""Deterministic course-level quality checks for Lesson Content V2."""

from __future__ import annotations

import json
import re
import hashlib
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from content_contract import (
    CAPABILITY_STAGES,
    CONTENT_FIELD_NAMES,
    EVALUATION_CRITERIA,
    EVALUATION_CRITERION_IDS,
    EVALUATION_SCORE_MAX,
    EVALUATION_SCORE_MIN,
    EVALUATION_SCORE_STEP,
    IMPLEMENTATION_STAGE_FIELDS,
    IN_CLASS_STAGE_IDS,
    IMPLEMENTATION_STAGE_IDS,
    format_implementation_stage,
    format_reflection,
    format_title,
    lesson_content_field_values,
)


# This starts at the level where a repeated Chinese sentence is substantive,
# while allowing short labels and shared technical terms to recur.
MIN_SENTENCE_LENGTH = 12
REPEATED_SENTENCE_LESSON_COUNT = 3
# The threshold is deliberately aligned with the old six-lesson baseline
# (0.8827 maximum SequenceMatcher score), while new fixtures remain below it.
WHOLE_LESSON_SIMILARITY_THRESHOLD = 0.85
# The calibration tests exercise copy+rename, 20% wording edits, synonym/word
# order edits, and genuinely different lessons.  The adjacent threshold is
# lower because a copied neighboring lesson is actionable even when its whole
# text score is diluted by otherwise different fields.
FIELD_SIMILARITY_THRESHOLD = 0.85
ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD = 0.78
ADJACENT_FIELD_SIMILARITY_THRESHOLD = 0.78
IMPLEMENTATION_SIMILARITY_THRESHOLD = 0.85
ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD = 0.78
IMPLEMENTATION_DUPLICATE_LESSON_COUNT = 3

# Structural repetition is deliberately a separate signal.  It is applied to
# sufficiently long narrative items after masking task-specific entities, so
# a shared verb or a recurring tool name cannot fail a lesson by itself.
STRUCTURAL_SIMILARITY_THRESHOLD = 0.86
ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD = 0.82
IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD = 0.84
ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD = 0.80
STRUCTURAL_MIN_ITEM_LENGTH = 18
STRUCTURAL_MIN_ACTIONS = 1
STRUCTURAL_SHORT_FIELDS = ("student_analysis.", "goals.", "reflection.")
PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD = 0.052
# The calibrated positive corpus starts at .176 and the largest negative score
# is 0 after removing the generic "方案" token. The existing cross-domain
# fixture scores .0502, so .045 preserves it while remaining well below a
# calibrated positive pair.
PROGRESSION_DECLARED_BOUNDARY_THRESHOLD = 0.045
PROGRESSION_SEQUENCE_THRESHOLD = 0.018
PROGRESSION_MIN_BIGRAM_SIGNAL = 0.025
PROGRESSION_MIN_TRIGRAM_SIGNAL = 0.012
PROGRESSION_MIN_SEQUENCE_SIGNAL = 0.085
EVALUATION_REMARK_MIN_CHARS = 4
CONTENT_V2_EVALUATION_REMARK_MAX_CHARS = 48
EVALUATION_REMARK_FIXED_CRITERIA = frozenset({"attendance", "compliance", "habits"})
EVALUATION_REMARK_CONTENT_CRITERIA = frozenset(
    {"participation", "discussion", "homework", "practice", "presentation", "improvement"}
)
REUSE_NARRATIVE_STRICT = "narrative_strict"
REUSE_TERMINOLOGY = "terminology_reusable"
REUSE_RESOURCE = "resource_reusable"
REUSE_REFERENCE = "reference_reusable"
REUSE_FIXED_RUBRIC = "fixed_rubric_reusable"
REUSE_IGNORE = "ignore"
PROGRESSION_STOPWORDS = (
    "完成",
    "任务",
    "学习",
    "记录",
    "成果",
    "学生",
    "本课",
    "下一课",
    "进行",
    "相关",
    "能够",
    "依据",
    "形成",
    "方案",
)
PROGRESSION_GENERIC_ANCHOR_VOCABULARY = frozenset(
    {
        *PROGRESSION_STOPWORDS,
        "设计",
        "操作",
        "分析",
        "检查",
        "流程",
        "使用",
        "开展",
        "执行",
        "处理",
        "实施",
    }
)
ACTION_MARKERS = (
    "分析",
    "设计",
    "编写",
    "执行",
    "核对",
    "整理",
    "判断",
    "评估",
    "操作",
    "测量",
    "制定",
    "调试",
    "测试",
    "配置",
    "验证",
    "提交",
    "复盘",
    "改进",
    "实现",
    "部署",
    "查询",
    "维护",
    "训练",
    "演示",
    "说明",
    "解释",
    "理解",
    "掌握",
    "识别",
    "阐明",
    "描述",
    "区分",
    "检查",
    "核验",
    "编排",
)
ENTITY_ACTION_WORDS = frozenset(
    {
        *ACTION_MARKERS,
        "比较",
        "标注",
        "定位",
        "确认",
        "检验",
        "证明",
        "支持",
        "说明",
        "复核",
        "追查",
        "回看",
        "保持",
        "留下",
        "发现",
        "拆解",
        "拆开",
        "补充",
        "调整",
        "联系",
        "涉及",
        "接触",
        "转成",
        "写入",
        "安排",
        "保留",
        "落实",
        "对应",
        "要求",
        "需要",
        "可以",
        "能够",
        "为什么",
        "如何",
        "怎样",
    }
)
ENTITY_NOUN_SUFFIXES = (
    "数据库",
    "任务单",
    "检查表",
    "记录表",
    "成果包",
    "数据集",
    "清单",
    "字典",
    "日志",
    "矩阵",
    "报告",
    "方案",
    "计划",
    "策略",
    "流程",
    "工具",
    "模型",
    "对象",
    "字段",
    "类型",
    "规则",
    "约束",
    "视图",
    "索引",
    "事务",
    "权限",
    "备份",
    "指标",
    "样例",
    "凭证",
    "账簿",
    "科目",
    "账户",
    "报表",
    "余额",
    "差错",
    "患者",
    "护理",
    "血压",
    "体温",
    "药物",
    "皮肤",
    "风险",
    "关系",
    "边界",
    "证据",
    "资料",
    "材料",
    "系统",
    "接口",
    "代码",
    "资源",
    "业务",
    "结果",
)
REFERENCE_SPECIFIC_PATTERN = re.compile(
    r"(?:isbn\s*[-:]?\s*[0-9x-]+|gb\s*[/-]?\s*t|标准编号|文件编号|出版社|作者|"
    r"(?:19|20)\d{2}\s*年?|第\s*[一二三四五六七八九十百0-9]+\s*版|版次)",
    re.IGNORECASE,
)
REFERENCE_EVIDENCE_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
REFERENCE_EVIDENCE_LOCATOR_PATTERN = re.compile(
    r"(?:官方|政府|教育部|国家卫生健康|行业协会).*(?:官网|章节|条款|第[一二三四五六七八九十百0-9]+[章节条]|页|文号|检索|路径)",
)

BOILERPLATE_PATTERNS = (
    "已具备相关课程基础",
    "理论知识向任务迁移",
    "任务驱动、教师示范、分组实训、过程评价",
    "培养规范操作、职业责任和质量意识",
    "项目教学法、任务驱动法、演示法",
    "提供模板清单、分步演示",
    "多数学生能按要求完成",
    "学生参与度较高",
    "后续增加优秀成果样例",
    "标准机房、多媒体设备、网络环境",
    "课程PPT、微课视频、任务单、评分表和成果模板",
)
REPEATED_SENTENCE_ALLOWLIST = frozenset({"线上+线下", "课堂小结", "项目实训"})
NON_IT_CONTAMINATION_TERMS = (
    "软件技术",
    "标准机房",
    "脚本",
    "截图工具",
    "代码编辑器",
    "数据安全",
)
NON_IT_CONTAMINATION_SCOPE = "template_or_generator_injected_defaults_only"


class ContentQualityError(ValueError):
    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


DIAGNOSTIC_PREVIEW_MAX_CHARS = 120
INTRA_GENERIC_TWO_CHAR_ANCHORS = frozenset(
    {"数据", "结果", "记录", "流程", "内容", "方法", "任务", "方案", "问题", "过程", "系统", "项目", "要求", "工作"}
)

# Implementation coherence is deliberately narrower than a general-purpose
# language classifier.  Only stable pedagogical labels/modalities and a small
# set of facilitation sentence shapes may stand on their own; domain-bearing
# items still have to connect to the lesson's main semantic component.
IMPLEMENTATION_ITEM_FIELDS = (
    "label",
    "modality",
    "content",
    "teacher_actions",
    "student_actions",
    "objective",
)
IMPLEMENTATION_GENERIC_PEDAGOGICAL_ITEMS = frozenset(
    {
        "课前准备",
        "任务导入",
        "案例导入",
        "任务介绍",
        "方法示范",
        "方法演示",
        "操作演示",
        "写法示范",
        "任务实施",
        "任务拓展",
        "诊断拓展",
        "项目实训",
        "组间互评",
        "小组诊断",
        "同伴校审",
        "成果展示",
        "课堂小结",
        "课堂总结",
        "课后完善",
        "线上",
        "线下",
        "线上线下",
        "线上+线下",
        "讲授",
        "演示",
        "实训",
        "实践",
        "小组实训",
        "小组研讨",
        "小组讨论",
        "小组协作",
        "任务驱动",
        "情境模拟",
        "教师巡视",
        "教师指导",
        "教师演示",
        "教师讲授",
        "教师点评",
        "教师总结",
        "教师组织课堂活动",
        "组织课堂活动",
        "组织快速互审",
        "学生讨论",
        "学生实践",
        "学生展示",
        "学生记录",
        "学生复述",
        "分组展示",
        "完成练习",
        "提交成果",
        "形成成果",
        "形成阶段成果",
        "形成可复核成果",
        "记录",
        "总结",
    }
)
IMPLEMENTATION_GENERIC_PEDAGOGICAL_SUFFIXES = (
    "准备",
    "导入",
    "介绍",
    "示范",
    "演示",
    "练习",
    "演练",
    "实训",
    "实践",
    "研讨",
    "讨论",
    "协作",
    "复核",
    "交付",
    "互评",
    "互查",
    "互审",
    "校审",
    "观察",
    "诊断",
    "判断",
    "核对",
    "复盘",
    "总结",
    "推演",
    "外显",
    "轮换",
    "辨析",
    "决策",
    "联结",
    "修订",
    "跟踪",
    "回收",
    "封装",
    "整理",
    "交接",
    "制证",
    "编表",
    "勾稽",
    "清点",
    "串联",
    "升级",
    "匹配",
    "预习",
)
IMPLEMENTATION_SUBSTANTIVE_MARKERS = (
    "sql",
    "数据库",
    "索引",
    "患者",
    "血压",
    "java",
    "er图",
    "代码",
    "凭证",
    "记账",
    "会计",
    "账簿",
    "科目",
    "账户",
    "制证",
    "编表",
    "票据",
    "单据",
)
IMPLEMENTATION_GENERIC_ACTION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^(?:教师|学生)?(?:巡视|指导|点评|总结)",
        r"^(?:熟悉|示范|指出|批注|组织|连接|逐项示范|提升.+能力)",
        r"^(?:根据|分配|提出|复述|把|提供|将|核验|掌握|引导|归纳|标注|追问|给出|为|建立|分工|依据|按|让|口头|串联|说明|尝试)",
        r"^反馈.+",
        r"^呈现.+",
        r"^记录分类依据",
        r"^形成.+(?:信息|成果)$",
        r"^(?:提交|上传).*(?:修订|成果|疑点|报告|记录)",
        r"^记录.+(?:口述|材料|顺序|时间压力|个人贡献|后续能力目标|措辞)",
        r"^收集.+(?:材料|经验)$",
        r"^收集材料",
        r"^记录材料",
        r"^呈现.+(?:要求|问题)$",
        r"^复盘.+(?:贡献|目标)$",
        r"^展示.+材料包$",
        r"^提出哪些.+",
        r"^补充一张.+",
        r"^写出.+理由$",
        r"^对比是否.+",
        r"^修正.+判断$",
        r"^交付.+业务$",
        r"^明确.+(?:任务|要求)$",
        r"^检验.+(?:步骤|习惯|成果)$",
        r"^统一.+反馈.+",
        r"^从审核者.+",
        r"^从案例中.+",
        r"^界定.+",
        r"^将.+(?:评语|证据|档|步骤|指令)$",
        r"^指定.+",
        r"^回收.+",
        r"^完成一次.+(?:成果展示|项目交付)$",
    )
)

# Existing accounting fixtures use conventional aliases (票据/单据,
# 制证/凭证, 账户/核算).  These are deterministic anchor equivalences, not
# a new semantic classifier, and are used only for implementation items.
IMPLEMENTATION_ANCHOR_ALIAS_GROUPS = (
    frozenset({"票据", "单据", "凭证"}),
    frozenset({"制证", "凭证", "记账"}),
    frozenset({"编表", "试算", "平衡表", "核算", "账户"}),
    frozenset({"会计", "账簿", "科目", "借贷", "核算", "账户", "凭证"}),
    frozenset({"错行", "差错", "错误", "差异", "更正", "审核", "复核"}),
)


def _diagnostic_fragment(value: Any, *, limit: int = DIAGNOSTIC_PREVIEW_MAX_CHARS) -> dict[str, str]:
    """Expose only a bounded preview plus a stable digest in QA diagnostics."""

    normalized = _normalize(value)
    meaningful = re.sub(r"\s+", "", normalized)
    preview = normalized[:limit]
    if len(preview) < len(normalized):
        preview = normalized[: max(1, limit - 1)].rstrip() + "…"
    return {"preview": preview, "text_sha256": hashlib.sha256(meaningful.encode("utf-8")).hexdigest()}


def _normalize(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(r"(?:^|\n)\s*\d+[.)、]\s*", "\n", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_item(value: Any) -> str:
    """Normalize one list item without allowing punctuation or numbering to hide reuse."""

    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"(?:^|\n)\s*\d+[.)、]\s*", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return "".join(char.casefold() for char in normalized if not unicodedata.category(char).startswith("P"))


def _meaningful_length(value: Any) -> int:
    return len(re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).strip())


def _implementation_items(stage: dict[str, Any], field: str) -> list[Any]:
    value = stage.get(field, "")
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value] if value is not None and str(value).strip() else []


def _is_generic_implementation_item(field: str, value: Any) -> bool:
    """Return whether one implementation item is a stable generic action."""

    normalized = _normalize_item(value)
    if not normalized:
        return True
    if normalized in {
        _normalize_item(item) for item in IMPLEMENTATION_GENERIC_PEDAGOGICAL_ITEMS
    }:
        return True
    if any(marker in normalized for marker in IMPLEMENTATION_SUBSTANTIVE_MARKERS):
        return False
    if field in {"label", "modality"} and any(
        normalized.endswith(suffix) for suffix in IMPLEMENTATION_GENERIC_PEDAGOGICAL_SUFFIXES
    ):
        return True
    if field in {"teacher_actions", "student_actions", "objective"}:
        return any(pattern.search(normalized) for pattern in IMPLEMENTATION_GENERIC_ACTION_PATTERNS)
    return False


def _implementation_anchor_evidence(left: Any, right: Any) -> dict[str, Any]:
    """Add only deterministic domain aliases to the existing intra anchor gate."""

    evidence = _intra_anchor_evidence(left, right)
    if evidence["status"] == "passed":
        return evidence
    left_text = _normalize_item(left)
    right_text = _normalize_item(right)
    for group in IMPLEMENTATION_ANCHOR_ALIAS_GROUPS:
        left_matches = sorted(term for term in group if _normalize_item(term) in left_text)
        right_matches = sorted(term for term in group if _normalize_item(term) in right_text)
        if not left_matches or not right_matches:
            continue
        result = dict(evidence)
        result.update(
            {
                "status": "passed",
                "reason": "shared deterministic implementation domain alias",
                "matched_fragments": [f"{left_matches[0]}/{right_matches[0]}"],
                "longest_substantive_match": left_matches[0],
                "substantive_residuals": [left_matches[0]],
                "evidence_strength": max(2, len(left_matches[0])),
                "score": round(min(1.0, max(2, len(left_matches[0])) / 12), 4),
            }
        )
        return result
    return evidence


def _item_values(lesson: dict[str, Any]) -> dict[str, list[str]]:
    """Expose list items individually so short repeated items cannot hide in a joined field."""

    result: dict[str, list[str]] = {
        "student_analysis.base": list(lesson["student_analysis"]["base"]),
        "student_analysis.problems": list(lesson["student_analysis"]["problems"]),
        "student_analysis.strategies": list(lesson["student_analysis"]["strategies"]),
        "teaching_content": list(lesson["teaching_content"]),
        "goals.knowledge": list(lesson["goals"]["knowledge"]),
        "goals.ability": list(lesson["goals"]["ability"]),
        "goals.quality": list(lesson["goals"]["quality"]),
        "key_point.content": list(lesson["key_point"]["content"]),
        "key_point.strategy": list(lesson["key_point"]["strategy"]),
        "difficult_point.content": list(lesson["difficult_point"]["content"]),
        "difficult_point.strategy": list(lesson["difficult_point"]["strategy"]),
        "teaching_methods": list(lesson["teaching_methods"]),
        "resources": list(lesson["resources"]),
        "references": [reference["text"] for reference in lesson["references"]],
    }
    for stage in lesson["implementation"]:
        stage_id = str(stage["id"])
        for field_name in ("content", "teacher_actions", "student_actions"):
            result[f"implementation.{stage_id}.{field_name}"] = list(stage[field_name])
        result[f"implementation.{stage_id}.objective"] = [stage["objective"]]
    for field_name in ("prior_learning", "deliverable", "next_bridge"):
        result[f"progression.{field_name}"] = [lesson["progression"][field_name]]
    for field_name in ("summary", "innovation", "improvement"):
        result[f"reflection.{field_name}"] = [lesson["reflection"][field_name]]
    for criterion in EVALUATION_CRITERIA:
        criterion_id = criterion[0]
        result[f"evaluation.remarks.{criterion_id}"] = [lesson["evaluation"]["remarks"][criterion_id]]
    return result


def _course_terms(lessons: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for lesson in lessons:
        for value in (
            lesson.get("unit", ""),
            lesson.get("task", ""),
            lesson.get("progression", {}).get("deliverable", ""),
        ):
            normalized = _normalize_item(value)
            if len(normalized) >= 2:
                terms.add(normalized)
    return terms


def reuse_policy(field: str) -> str:
    """Return the single authoritative reuse class for every QA detector."""

    if field in {"course_name", "major", "audience", "stage_id", "rubric_label", "bookmark_name"}:
        return REUSE_IGNORE
    if field == "teaching_methods":
        return REUSE_TERMINOLOGY
    if field == "resources":
        return REUSE_RESOURCE
    if field == "references":
        return REUSE_REFERENCE
    if field.startswith("evaluation.remarks."):
        criterion = field.rsplit(".", 1)[-1]
        if criterion in EVALUATION_REMARK_FIXED_CRITERIA:
            return REUSE_FIXED_RUBRIC
    return REUSE_NARRATIVE_STRICT


def _is_allowed_repeated_item(field: str, value: str, course_terms: set[str]) -> bool:
    """Apply the shared policy; short-term exemptions never enter narrative fields."""

    normalized = _normalize_item(value)
    if not normalized:
        return True
    # course_terms remains in the signature for compatibility with callers,
    # but can only inform reusable categories.  A short course term in a
    # narrative field is still subject to duplicate and skeleton detection.
    _ = course_terms
    return reuse_policy(field) != REUSE_NARRATIVE_STRICT


def _sentences(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value))
    parts = re.split(r"[。！？!?；;\n]+", text)
    result = []
    for part in parts:
        normalized = _normalize(part)
        if len(normalized) >= MIN_SENTENCE_LENGTH and normalized not in REPEATED_SENTENCE_ALLOWLIST:
            result.append(normalized)
    return result


def _joined(values: Any) -> str:
    if isinstance(values, list):
        return "\n".join(_normalize(item) for item in values)
    if isinstance(values, dict):
        return "\n".join(_joined(values[key]) for key in sorted(values))
    return _normalize(values)


def _lesson_id(lesson: dict[str, Any], index: int) -> str:
    return str(lesson.get("lesson_id") or f"lesson-{index}")


def _field_groups(lesson: dict[str, Any]) -> dict[str, str]:
    analysis = lesson["student_analysis"]
    goals = lesson["goals"]
    progression = lesson["progression"]
    return {
        "student_analysis.base": _joined(analysis["base"]),
        "student_analysis.problems": _joined(analysis["problems"]),
        "student_analysis.strategies": _joined(analysis["strategies"]),
        "teaching_content": _joined(lesson["teaching_content"]),
        "goals.knowledge": _joined(goals["knowledge"]),
        "goals.ability": _joined(goals["ability"]),
        "goals.quality": _joined(goals["quality"]),
        "key_point.content": _joined(lesson["key_point"]["content"]),
        "key_point.strategy": _joined(lesson["key_point"]["strategy"]),
        "difficult_point.content": _joined(lesson["difficult_point"]["content"]),
        "difficult_point.strategy": _joined(lesson["difficult_point"]["strategy"]),
        "teaching_methods": _joined(lesson["teaching_methods"]),
        "progression.prior_learning": _normalize(progression["prior_learning"]),
        "progression.deliverable": _normalize(progression["deliverable"]),
        "progression.next_bridge": _normalize(progression["next_bridge"]),
        "reflection.summary": _normalize(lesson["reflection"]["summary"]),
        "reflection.innovation": _normalize(lesson["reflection"]["innovation"]),
        "reflection.improvement": _normalize(lesson["reflection"]["improvement"]),
        **{
            f"evaluation.remarks.{criterion_id}": _normalize(lesson["evaluation"]["remarks"][criterion_id])
            for criterion_id in EVALUATION_CRITERION_IDS
        },
    }


def _lesson_narrative(lesson: dict[str, Any]) -> str:
    values = {
        field: value
        for field, value in _field_groups(lesson).items()
        if reuse_policy(field) == REUSE_NARRATIVE_STRICT
    }
    values["implementation"] = "\n".join(
        "\n".join(
            _joined(stage[field_name])
            for field_name in IMPLEMENTATION_STAGE_FIELDS
        )
        for stage in lesson["implementation"]
    )
    return "\n".join(_normalize(values[key]) for key in sorted(values))


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", _normalize(value))
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def _similarity(left: str, right: str) -> tuple[float, float]:
    sequence = SequenceMatcher(None, left, right).ratio()
    left_grams = _character_ngrams(left)
    right_grams = _character_ngrams(right)
    union = left_grams | right_grams
    jaccard = len(left_grams & right_grams) / len(union) if union else 1.0
    return sequence, jaccard


def _top_fragments(left: str, right: str) -> list[str]:
    matcher = SequenceMatcher(None, left, right)
    fragments = []
    for block in matcher.get_matching_blocks():
        fragment = _normalize(left[block.a : block.a + block.size])
        if len(fragment) >= MIN_SENTENCE_LENGTH:
            fragments.append(fragment)
    return sorted(set(fragments), key=lambda value: (-len(value), value))[:3]


def _bounded_fragments(fragments: list[str]) -> tuple[list[str], list[str]]:
    records = [_diagnostic_fragment(value) for value in fragments]
    return [record["preview"] for record in records], [record["text_sha256"] for record in records]


def _entity_fragments(lesson: dict[str, Any]) -> set[str]:
    """Collect only lesson-specific noun-like phrases for structural masking."""

    candidates: list[str] = [
        str(lesson.get("unit", "")),
        str(lesson.get("task", "")),
        str(lesson.get("progression", {}).get("deliverable", "")),
        str(lesson.get("progression", {}).get("next_bridge", "")),
    ]
    candidates.extend(str(value) for value in lesson.get("resources", []))
    candidates.extend(str(value) for value in lesson.get("teaching_content", []))
    candidates.extend(str(value) for value in lesson.get("key_point", {}).get("content", []))
    candidates.extend(str(value) for value in lesson.get("difficult_point", {}).get("content", []))
    candidates.extend(str(value) for value in lesson.get("goals", {}).get("knowledge", []))
    fragments: set[str] = set()
    split_words = sorted(
        {
            *ENTITY_ACTION_WORDS,
            *PROGRESSION_GENERIC_ANCHOR_VOCABULARY,
            "提交",
            "完成",
            "形成",
            "编写",
            "整理",
            "输出",
            "建立",
            "制作",
            "记录",
            "依据",
            "针对",
            "使用",
            "进入",
            "围绕",
            "通过",
        },
        key=lambda item: (-len(item), item),
    )
    split_pattern = "|".join(re.escape(word) for word in split_words)
    for candidate in candidates:
        normalized = _normalize(candidate)
        for fragment in re.split(
            rf"[，,、。；;：:（）()\[\]【】/\\\s]+|{split_pattern}|并|以及|和|与|将|按",
            normalized,
        ):
            fragment = re.sub(r"^第(?:\d+|[一二三四五六七八九十百]+)课", "", _normalize(fragment))
            fragment = fragment.strip("的地得了在中内外前后上下")
            if (
                3 <= _meaningful_length(fragment) <= 12
                and fragment not in PROGRESSION_GENERIC_ANCHOR_VOCABULARY
                and not any(word in fragment for word in ENTITY_ACTION_WORDS)
                and (
                    fragment.endswith(ENTITY_NOUN_SUFFIXES)
                    or bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+-]{1,11}", fragment))
                )
            ):
                fragments.add(fragment)
    return fragments


def _mask_entities(value: Any, entities: set[str]) -> str:
    masked = _normalize(value)
    for entity in sorted(entities, key=lambda item: (-_meaningful_length(item), item)):
        if _meaningful_length(entity) >= 3:
            masked = masked.replace(entity, "<ENTITY>")
    masked = re.sub(r"\d+(?:\.\d+)?", "<NUMBER>", masked)
    return masked


def _similarity_score(sequence: float, jaccard: float) -> float:
    """Combine order and overlap evidence without letting one weak metric win alone."""

    return 0.55 * sequence + 0.45 * jaccard


def _structural_record(
    *,
    left_id: str,
    right_id: str,
    field: str,
    left_text: str,
    right_text: str,
    raw_sequence: float,
    raw_jaccard: float,
    masked_left: str,
    masked_right: str,
    masked_sequence: float,
    masked_jaccard: float,
    adjacent: bool,
    indices: tuple[int, int] | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    top_fragments, top_fragment_hashes = _bounded_fragments(_top_fragments(masked_left, masked_right))
    record: dict[str, Any] = {
        "lessons": [left_id, right_id],
        "field": field,
        "score": round(_similarity_score(masked_sequence, masked_jaccard), 4),
        "raw_score": round(_similarity_score(raw_sequence, raw_jaccard), 4),
        "masked_score": round(_similarity_score(masked_sequence, masked_jaccard), 4),
        "raw_sequence_matcher": round(raw_sequence, 4),
        "raw_character_3gram_jaccard": round(raw_jaccard, 4),
        "masked_sequence_matcher": round(masked_sequence, 4),
        "masked_character_3gram_jaccard": round(masked_jaccard, 4),
        "masked_fingerprint": _normalize(masked_left)[:DIAGNOSTIC_PREVIEW_MAX_CHARS],
        "masked_fingerprint_sha256": hashlib.sha256(_normalize(masked_left).encode("utf-8")).hexdigest(),
        "top_fragments": top_fragments,
        "top_fragment_sha256": top_fragment_hashes,
        "top_repeated_fragments": top_fragments,
        "top_repeated_fragment_sha256": top_fragment_hashes,
        "adjacent": adjacent,
        "reuse_policy": reuse_policy(field),
    }
    if indices is not None:
        record["item_indices"] = list(indices)
    if stage is not None:
        record["stage"] = stage
    return record


def _structural_item_pairs(
    values: dict[str, dict[str, list[str]]],
    lesson_ids: list[str],
    lessons_by_id: dict[str, dict[str, Any]],
    *,
    threshold: float,
    adjacent_threshold: float,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        if reuse_policy(field) != REUSE_NARRATIVE_STRICT:
            continue
        for left_index, left_id in enumerate(lesson_ids):
            for right_id in lesson_ids[left_index + 1 :]:
                adjacent = _is_adjacent(left_index, positions[right_id])
                effective_threshold = adjacent_threshold if adjacent else threshold
                entities = _entity_fragments(lessons_by_id[left_id]) | _entity_fragments(lessons_by_id[right_id])
                for left_item_index, left_text in enumerate(per_lesson.get(left_id, []), 1):
                    for right_item_index, right_text in enumerate(per_lesson.get(right_id, []), 1):
                        short_structural_field = field.startswith(STRUCTURAL_SHORT_FIELDS)
                        minimum_length = 8 if short_structural_field else STRUCTURAL_MIN_ITEM_LENGTH
                        if min(_meaningful_length(left_text), _meaningful_length(right_text)) < minimum_length:
                            continue
                        if not short_structural_field and not any(marker in f"{left_text}{right_text}" for marker in ACTION_MARKERS):
                            continue
                        masked_left = _mask_entities(left_text, entities)
                        masked_right = _mask_entities(right_text, entities)
                        raw_sequence, raw_jaccard = _similarity(_normalize(left_text), _normalize(right_text))
                        masked_sequence, masked_jaccard = _similarity(masked_left, masked_right)
                        masked_score = _similarity_score(masked_sequence, masked_jaccard)
                        if masked_score < effective_threshold:
                            continue
                        # Entity masking must reveal a shared skeleton, not
                        # manufacture one by reducing two unrelated short
                        # phrases to the same pair of placeholders.
                        if raw_sequence < 0.45 and raw_jaccard < 0.25:
                            continue
                        pairs.append(
                            _structural_record(
                                left_id=left_id,
                                right_id=right_id,
                                field=field,
                                left_text=left_text,
                                right_text=right_text,
                                raw_sequence=raw_sequence,
                                raw_jaccard=raw_jaccard,
                                masked_left=masked_left,
                                masked_right=masked_right,
                                masked_sequence=masked_sequence,
                                masked_jaccard=masked_jaccard,
                                adjacent=adjacent,
                                indices=(left_item_index, right_item_index),
                                stage=field.split(".")[1] if field.startswith("implementation.") else None,
                            )
                        )
    return sorted(
        pairs,
        key=lambda item: (-item["masked_score"], item["field"], item["lessons"], item.get("item_indices", [])),
    )


def _record_duplicate_groups(values: dict[str, dict[str, str]], minimum: int = 2) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for field, per_lesson in values.items():
        by_value: dict[str, list[str]] = {}
        for lesson_id, value in per_lesson.items():
            normalized = _normalize(value)
            if normalized:
                by_value.setdefault(normalized, []).append(lesson_id)
        for value, lesson_ids in by_value.items():
            if len(lesson_ids) >= minimum:
                diagnostic = _diagnostic_fragment(value)
                groups.append(
                    {
                        "field": field,
                        "lessons": sorted(lesson_ids),
                        "text": diagnostic["preview"],
                        "text_sha256": diagnostic["text_sha256"],
                        "reuse_policy": reuse_policy(field),
                    }
                )
    return sorted(groups, key=lambda item: (item["field"], item["lessons"]))


def _all_content_strings(lesson: dict[str, Any]) -> dict[str, list[str]]:
    values = lesson_content_field_values(lesson)
    result = {name: [values[name]] for name in CONTENT_FIELD_NAMES}
    result["progression"] = [_joined(lesson["progression"])]
    result["reflection"] = format_reflection(lesson["reflection"])
    result.update(
        {
            f"evaluation.remarks.{criterion_id}": [lesson["evaluation"]["remarks"][criterion_id]]
            for criterion_id in EVALUATION_CRITERION_IDS
        }
    )
    for stage in lesson["implementation"]:
        stage_id = str(stage["id"])
        for field_name in IMPLEMENTATION_STAGE_FIELDS:
            result[f"implementation.{stage_id}.{field_name}"] = [_joined(stage[field_name])]
    return result


def _completeness_report(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check meaningful text after schema validation, including whitespace-only values."""

    counts: dict[str, dict[str, int]] = {}
    errors: list[str] = []

    def check_text(lesson_id: str, field: str, value: Any, minimum: int = 3) -> None:
        if _meaningful_length(value) < minimum:
            errors.append(f"{lesson_id}.{field} does not contain meaningful content")

    for field_name in ("course_name", "major", "audience"):
        if _meaningful_length(data.get(field_name, "")) < 1:
            errors.append(f"course.{field_name} does not contain meaningful content")
    for index, lesson in enumerate(data.get("lessons", []), 1):
        lesson_id = _lesson_id(lesson, index)
        check_text(lesson_id, "unit", lesson.get("unit", ""))
        check_text(lesson_id, "task", lesson.get("task", ""))
        analysis = lesson["student_analysis"]
        goals = lesson["goals"]
        counts[lesson_id] = {
            "student_base": len(analysis["base"]),
            "student_problems": len(analysis["problems"]),
            "student_strategies": len(analysis["strategies"]),
            "teaching_content": len(lesson["teaching_content"]),
            "knowledge_goals": len(goals["knowledge"]),
            "ability_goals": len(goals["ability"]),
            "quality_goals": len(goals["quality"]),
            "teaching_methods": len(lesson["teaching_methods"]),
            "resources": len(lesson["resources"]),
            "references": len(lesson["references"]),
            "implementation_stages": len(lesson["implementation"]),
        }
        for field_name in ("base", "problems", "strategies"):
            for item_index, value in enumerate(analysis[field_name], 1):
                check_text(lesson_id, f"student_analysis.{field_name}[{item_index}]", value)
        for field_name in ("teaching_content", "teaching_methods", "resources"):
            for item_index, value in enumerate(lesson[field_name], 1):
                check_text(lesson_id, f"{field_name}[{item_index}]", value)
        for item_index, reference in enumerate(lesson["references"], 1):
            check_text(lesson_id, f"references[{item_index}]", reference["text"])
        for goal_name in ("knowledge", "ability", "quality"):
            for item_index, value in enumerate(goals[goal_name], 1):
                check_text(lesson_id, f"goals.{goal_name}[{item_index}]", value)
        for point_name in ("key_point", "difficult_point"):
            for list_name in ("content", "strategy"):
                for item_index, value in enumerate(lesson[point_name][list_name], 1):
                    check_text(lesson_id, f"{point_name}.{list_name}[{item_index}]", value)
        for field_name in ("prior_learning", "deliverable", "next_bridge"):
            check_text(lesson_id, f"progression.{field_name}", lesson["progression"][field_name], 6)
        check_text(lesson_id, "progression.capability_stage", lesson["progression"].get("capability_stage", ""), 1)
        for stage in lesson["implementation"]:
            stage_id = str(stage["id"])
            check_text(lesson_id, f"implementation.{stage_id}.label", stage.get("label", ""), 1)
            check_text(lesson_id, f"implementation.{stage_id}.modality", stage.get("modality", ""), 1)
            for field_name in ("content", "teacher_actions", "student_actions"):
                for item_index, value in enumerate(stage[field_name], 1):
                    check_text(lesson_id, f"implementation.{stage_id}.{field_name}[{item_index}]", value)
            check_text(lesson_id, f"implementation.{stage_id}.objective", stage["objective"], 6)
        for field_name in ("summary", "innovation", "improvement"):
            check_text(lesson_id, f"reflection.{field_name}", lesson["reflection"][field_name], 12)
        for criterion_id in EVALUATION_CRITERION_IDS:
            check_text(
                lesson_id,
                f"evaluation.remarks.{criterion_id}",
                lesson["evaluation"]["remarks"].get(criterion_id, ""),
                EVALUATION_REMARK_MIN_CHARS,
            )

    return {"lessons": counts, "meaningful_errors": errors}, errors


def _density_report(data: dict[str, Any], manifest: dict[str, Any] | None) -> tuple[list[dict[str, Any]], int]:
    errors: list[dict[str, Any]] = []
    total_chars = 0
    fields = manifest.get("fields", {}) if manifest else {}
    for index, lesson in enumerate(data["lessons"], 1):
        lesson_id = _lesson_id(lesson, index)
        title = format_title(index, data, lesson)
        title_spec = fields.get("title", {})
        title_limit = title_spec.get("max_chars")
        if title_limit is not None and len(title) > int(title_limit):
            errors.append({"lesson": lesson_id, "field": "title", "actual_chars": len(title), "limit": int(title_limit)})
        values = lesson_content_field_values(lesson)
        for field_name, value in values.items():
            total_chars += len(value)
            spec = fields.get(field_name, {})
            max_chars = spec.get("max_chars")
            max_paragraphs = spec.get("max_paragraphs")
            if max_chars is not None and len(value) > int(max_chars):
                errors.append({"lesson": lesson_id, "field": field_name, "actual_chars": len(value), "limit": int(max_chars)})
            paragraphs = len(value.splitlines()) or 1
            if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                errors.append({"lesson": lesson_id, "field": field_name, "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        implementation_spec = fields.get("implementation", {})
        for stage in lesson["implementation"]:
            formatted = format_implementation_stage(stage)
            for cell_index, value in formatted.items():
                total_chars += len(value)
                max_chars = implementation_spec.get("max_chars")
                max_paragraphs = implementation_spec.get("max_paragraphs")
                if max_chars is not None and len(value) > int(max_chars):
                    errors.append({"lesson": lesson_id, "field": f"implementation.{stage['id']}.{cell_index}", "actual_chars": len(value), "limit": int(max_chars)})
                paragraphs = len(value.splitlines()) or 1
                if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                    errors.append({"lesson": lesson_id, "field": f"implementation.{stage['id']}.{cell_index}", "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        reflection_spec = fields.get("reflection", {})
        for name, value in zip(("summary", "innovation", "improvement"), format_reflection(lesson["reflection"])):
            total_chars += len(value)
            max_chars = reflection_spec.get("max_chars")
            max_paragraphs = reflection_spec.get("max_paragraphs")
            if max_chars is not None and len(value) > int(max_chars):
                errors.append({"lesson": lesson_id, "field": f"reflection.{name}", "actual_chars": len(value), "limit": int(max_chars)})
            paragraphs = len(value.splitlines()) or 1
            if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                errors.append({"lesson": lesson_id, "field": f"reflection.{name}", "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        evaluation_spec = fields.get("evaluation", {})
        manifest_limit = evaluation_spec.get("max_remark_chars")
        remark_limit = CONTENT_V2_EVALUATION_REMARK_MAX_CHARS
        if manifest_limit is not None:
            remark_limit = min(remark_limit, int(manifest_limit))
        for criterion_id in EVALUATION_CRITERION_IDS:
            value = _normalize(lesson["evaluation"]["remarks"][criterion_id])
            total_chars += len(value)
            if _meaningful_length(value) > remark_limit:
                errors.append(
                    {
                        "lesson": lesson_id,
                        "field": f"evaluation.remarks.{criterion_id}",
                        "actual_chars": _meaningful_length(value),
                        "limit": remark_limit,
                    }
                )
    return errors, total_chars


def _is_adjacent(left_index: int, right_index: int) -> bool:
    return right_index == left_index + 1


def _similarity_record(
    *,
    left_id: str,
    right_id: str,
    left_text: str,
    right_text: str,
    sequence: float,
    jaccard: float,
    field: str | None = None,
    stage: str | None = None,
    adjacent: bool = False,
) -> dict[str, Any]:
    top_fragments, top_fragment_hashes = _bounded_fragments(_top_fragments(left_text, right_text))
    record: dict[str, Any] = {
        "lessons": [left_id, right_id],
        "score": round(max(sequence, jaccard), 4),
        "sequence_matcher": round(sequence, 4),
        "character_3gram_jaccard": round(jaccard, 4),
        "top_fragments": top_fragments,
        "top_fragment_sha256": top_fragment_hashes,
        "top_repeated_fragments": top_fragments,
        "top_repeated_fragment_sha256": top_fragment_hashes,
        "adjacent": adjacent,
    }
    if field is not None:
        record["field"] = field
        record["reuse_policy"] = reuse_policy(field)
    if stage is not None:
        record["stage"] = stage
    return record


def _similarity_exceeds(sequence: float, jaccard: float, threshold: float) -> bool:
    """Use both order-sensitive and character-overlap evidence for paraphrase detection."""

    return sequence >= threshold or (jaccard >= threshold and sequence >= threshold - 0.12)


def _adjacent_exact_duplicates(
    values: dict[str, dict[str, str]],
    lesson_ids: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for field, per_lesson in values.items():
        for index in range(len(lesson_ids) - 1):
            left_id, right_id = lesson_ids[index : index + 2]
            left_text = _normalize(per_lesson.get(left_id, ""))
            right_text = _normalize(per_lesson.get(right_id, ""))
            if left_text and left_text == right_text:
                diagnostic = _diagnostic_fragment(left_text)
                records.append(
                    {
                        "lessons": [left_id, right_id],
                        "field": field,
                        "text": diagnostic["preview"],
                        "text_sha256": diagnostic["text_sha256"],
                        "score": 1.0,
                        "top_fragments": [diagnostic["preview"]],
                        "top_fragment_sha256": [diagnostic["text_sha256"]],
                        "top_repeated_fragments": [diagnostic["preview"]],
                        "top_repeated_fragment_sha256": [diagnostic["text_sha256"]],
                        "reuse_policy": reuse_policy(field),
                    }
                )
    return sorted(records, key=lambda item: (item["lessons"], item.get("field", "")))


def _item_duplicate_reports(
    values: dict[str, dict[str, list[str]]],
    lesson_ids: list[str],
    course_terms: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return all item duplicates, adjacent violations, and non-adjacent violations."""

    all_duplicates: list[dict[str, Any]] = []
    adjacent_violations: list[dict[str, Any]] = []
    frequency_violations: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        occurrences: dict[str, list[tuple[str, int, str]]] = {}
        for lesson_id in lesson_ids:
            for item_index, text in enumerate(per_lesson.get(lesson_id, []), 1):
                normalized = _normalize_item(text)
                if normalized:
                    occurrences.setdefault(normalized, []).append((lesson_id, item_index, _normalize(text)))
        for normalized, entries in occurrences.items():
            unique_lesson_ids = sorted({entry[0] for entry in entries}, key=lambda item: positions[item])
            if len(unique_lesson_ids) < 2:
                continue
            diagnostic = _diagnostic_fragment(entries[0][2])
            normalized_diagnostic = _diagnostic_fragment(normalized)
            record = {
                "field": field,
                "lessons": unique_lesson_ids,
                "count": len(unique_lesson_ids),
                "text": diagnostic["preview"],
                "text_sha256": diagnostic["text_sha256"],
                "normalized": normalized_diagnostic["preview"],
                "normalized_sha256": normalized_diagnostic["text_sha256"],
                "items": [
                    {"lesson": lesson_id, "index": item_index}
                    for lesson_id, item_index, _text in entries
                ],
                "allowed": _is_allowed_repeated_item(field, entries[0][2], course_terms),
                "reuse_policy": reuse_policy(field),
            }
            all_duplicates.append(record)
            if record["allowed"]:
                continue
            adjacent = any(
                positions[right] == positions[left] + 1
                for left, right in zip(unique_lesson_ids, unique_lesson_ids[1:])
            )
            if adjacent:
                adjacent_violations.append(record)
            if len(unique_lesson_ids) >= 3:
                frequency_violations.append(record)
    sort_key = lambda item: (item["field"], item["lessons"], item["normalized"])
    return (
        sorted(all_duplicates, key=sort_key),
        sorted(adjacent_violations, key=sort_key),
        sorted(frequency_violations, key=sort_key),
    )


def _pairwise_similarity(
    values: dict[str, dict[str, str]],
    lesson_ids: list[str],
    *,
    threshold: float,
    adjacent_threshold: float,
    implementation: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    adjacent_pairs: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        for left_index, left_id in enumerate(lesson_ids):
            for right_id in lesson_ids[left_index + 1 :]:
                left_text, right_text = per_lesson.get(left_id, ""), per_lesson.get(right_id, "")
                if min(len(left_text), len(right_text)) < 30:
                    continue
                adjacent = _is_adjacent(positions[left_id], positions[right_id])
                effective_threshold = adjacent_threshold if adjacent else threshold
                sequence, jaccard = _similarity(left_text, right_text)
                if not _similarity_exceeds(sequence, jaccard, effective_threshold):
                    continue
                stage = field.split(".", 1)[0] if implementation else None
                record = _similarity_record(
                    left_id=left_id,
                    right_id=right_id,
                    left_text=left_text,
                    right_text=right_text,
                    sequence=sequence,
                    jaccard=jaccard,
                    field=None if implementation else field,
                    stage=stage,
                    adjacent=adjacent,
                )
                pairs.append(record)
                if adjacent:
                    adjacent_pairs.append(record)
    pairs.sort(key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"]))
    adjacent_pairs.sort(key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"]))
    return pairs, adjacent_pairs


def _progression_signal_text(value: Any) -> str:
    text = _joined(value) if isinstance(value, (list, tuple, dict)) else _normalize(value)
    for stopword in PROGRESSION_STOPWORDS:
        text = text.replace(stopword, "")
    return re.sub(r"\s+", "", text)


def _progression_anchor_text(value: Any) -> str:
    text = _joined(value) if isinstance(value, (list, tuple, dict)) else _normalize(value)
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", text).casefold()


def _anchor_residual(fragment: str) -> str:
    residual = fragment
    for word in sorted(PROGRESSION_GENERIC_ANCHOR_VOCABULARY, key=lambda item: (-len(item), item)):
        residual = residual.replace(word.casefold(), "")
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", residual)


def _technical_acronyms(value: Any) -> dict[str, str]:
    text = _joined(value) if isinstance(value, (list, tuple, dict)) else _normalize(value)
    result: dict[str, str] = {}
    for match in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*(?![A-Za-z0-9])", text):
        display = match.group(0)
        key = re.sub(r"[-/]", "", display).casefold()
        if len(key) >= 2:
            result.setdefault(key, display)
    return result


def _progression_anchor_evidence(upstream: Any, downstream: Any) -> dict[str, Any]:
    """Prove that a progression link shares a concrete object, artifact, or acronym."""

    left = _progression_anchor_text(upstream)
    right = _progression_anchor_text(downstream)
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    candidates = {
        shorter[index : index + size]
        for size in range(2, min(12, len(shorter)) + 1)
        for index in range(0, len(shorter) - size + 1)
        if shorter[index : index + size] in longer
    }
    matched_fragments = sorted(
        (
            fragment
            for fragment in candidates
            if not any(fragment != other and fragment in other for other in candidates)
        ),
        key=lambda item: (-len(item), item),
    )
    substantive: list[tuple[str, str]] = []
    generic_only: list[str] = []
    for fragment in matched_fragments:
        residual = _anchor_residual(fragment)
        if len(residual) >= 2:
            substantive.append((fragment, residual))
        else:
            generic_only.append(fragment)

    left_acronyms = _technical_acronyms(upstream)
    right_acronyms = _technical_acronyms(downstream)
    acronym_matches = [left_acronyms[key] for key in sorted(left_acronyms.keys() & right_acronyms.keys())]
    unique_residuals = {residual for _fragment, residual in substantive}
    residual_total = sum(len(value) for value in unique_residuals)
    longest_pair = max(substantive, key=lambda item: (len(item[0]), len(item[1]), item[0]), default=("", ""))
    # A three-character-or-longer shared phrase with a concrete two-character
    # core is substantive (for example 需求分析 or 监测记录). Two
    # distinct concrete two-character fragments also establish the same link.
    chinese_anchor = bool(substantive) and (
        len(longest_pair[0]) >= 3 or residual_total >= 4
    )
    status = "passed" if chinese_anchor or acronym_matches else "failed"
    if acronym_matches:
        reason = "shared technical acronym"
    elif chinese_anchor:
        reason = "shared substantive artifact fragment"
    elif generic_only:
        reason = "overlap contains only generic progression actions"
    else:
        reason = "no shared substantive artifact anchor"
    return {
        "status": status,
        "matched_fragments": sorted(matched_fragments, key=lambda item: (-len(item), item))[:8],
        "longest_substantive_match": longest_pair[0],
        "acronym_matches": acronym_matches,
        "generic_only_matches": sorted(set(generic_only), key=lambda item: (-len(item), item))[:8],
        "substantive_residuals": sorted(unique_residuals, key=lambda item: (-len(item), item)),
        "evidence_strength": max(
            [len(longest_pair[1]), residual_total, *(len(re.sub(r"[-/]", "", item)) for item in acronym_matches)],
            default=0,
        ),
        "reason": reason,
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _progression_gate(upstream: Any, downstream: Any, threshold: float) -> dict[str, Any]:
    """Evaluate one directional progression claim with independent evidence."""

    anchor_evidence = _progression_anchor_evidence(upstream, downstream)
    upstream_signal = _progression_signal_text(upstream)
    downstream_signal = _progression_signal_text(downstream)
    sequence, _ = _similarity(upstream_signal, downstream_signal)
    bigrams_left = _character_ngrams(upstream_signal, 2)
    bigrams_right = _character_ngrams(downstream_signal, 2)
    trigrams_left = _character_ngrams(upstream_signal, 3)
    trigrams_right = _character_ngrams(downstream_signal, 3)
    bigram_jaccard = _jaccard(bigrams_left, bigrams_right)
    trigram_jaccard = _jaccard(trigrams_left, trigrams_right)
    weighted = 0.20 * sequence + 0.45 * bigram_jaccard + 0.35 * trigram_jaccard
    signal_count = sum(
        (
            bigram_jaccard >= PROGRESSION_MIN_BIGRAM_SIGNAL,
            trigram_jaccard >= PROGRESSION_MIN_TRIGRAM_SIGNAL,
            sequence >= PROGRESSION_MIN_SEQUENCE_SIGNAL,
        )
    )
    overlap = sorted(bigrams_left & bigrams_right, key=lambda value: (-len(value), value))[:5]
    lexical_status = "passed" if weighted >= threshold and signal_count >= 2 else "failed"
    return {
        "score": weighted,
        "sequence_matcher": sequence,
        "character_2gram_jaccard": bigram_jaccard,
        "character_3gram_jaccard": trigram_jaccard,
        "signal_count": signal_count,
        "top_overlap": overlap,
        "lexical_status": lexical_status,
        "substantive_anchor": anchor_evidence,
        "status": (
            "passed"
            if lexical_status == "passed" and anchor_evidence["status"] == "passed"
            else "failed"
        ),
    }


def _intra_anchor_evidence(left: Any, right: Any) -> dict[str, Any]:
    """Require a concrete multi-character or technical anchor for one lesson."""

    evidence = _progression_anchor_evidence(left, right)
    two_char_specific = any(
        len(item) == 2 and item not in INTRA_GENERIC_TWO_CHAR_ANCHORS
        for item in evidence["substantive_residuals"]
    )
    acceptable = (
        bool(evidence["acronym_matches"])
        or len(evidence["longest_substantive_match"]) >= 3
        or two_char_specific
    )
    # Two distinct concrete fragments can establish a domain, but a single
    # two-character overlap such as 数据/记录 is too generic for this gate.
    if not acceptable and len(evidence["substantive_residuals"]) >= 2:
        acceptable = sum(len(item) for item in evidence["substantive_residuals"]) >= 5
    result = dict(evidence)
    result["status"] = "passed" if acceptable else "failed"
    if acceptable and not evidence["reason"].startswith("shared"):
        result["reason"] = "shared substantive lesson anchor"
    elif not acceptable:
        result["reason"] = evidence["reason"]
    result["score"] = round(min(1.0, evidence["evidence_strength"] / 12), 4)
    return result


def _best_intra_item(left: Any, values: list[Any]) -> tuple[int, Any, dict[str, Any]] | None:
    """Return the strongest concrete body item for a shared-anchor bridge."""

    candidates = [
        (index, value, _intra_anchor_evidence(left, value))
        for index, value in enumerate(values)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (item[2]["status"] == "passed", item[2]["score"], -item[0]),
    )


def _intra_diagnostic_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep edge diagnostics bounded and free of complete user paragraphs."""

    return {
        key: evidence[key]
        for key in (
            "status",
            "score",
            "reason",
            "matched_fragments",
            "longest_substantive_match",
            "acronym_matches",
            "generic_only_matches",
            "substantive_residuals",
        )
        if key in evidence
    }


def _intra_lesson_coherence(lessons: list[dict[str, Any]], lesson_ids: list[str]) -> dict[str, Any]:
    """Require one substantive connected component for the lesson's main chain."""

    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    progression_fields = ("prior_learning", "next_bridge")
    boundary_stage_ids = {IMPLEMENTATION_STAGE_IDS[0], IMPLEMENTATION_STAGE_IDS[-1]}

    for lesson_id, lesson in zip(lesson_ids, lessons):
        body_fields = {
            "teaching_content": list(lesson.get("teaching_content", [])),
            "key_point.content": list(lesson.get("key_point", {}).get("content", [])),
            "difficult_point.content": list(lesson.get("difficult_point", {}).get("content", [])),
        }
        nodes: list[dict[str, Any]] = [
            {"id": "task", "kind": "task", "field": "task", "value": lesson.get("task", "")},
        ]
        for field, values in body_fields.items():
            for index, value in enumerate(values):
                nodes.append(
                    {"id": f"{field}[{index}]", "kind": "instructional_body", "field": field, "index": index, "value": value}
                )
        nodes.append(
            {
                "id": "deliverable",
                "kind": "deliverable",
                "field": "progression.deliverable",
                "value": lesson.get("progression", {}).get("deliverable", ""),
            }
        )
        node_by_id = {node["id"]: node for node in nodes}
        body_node_ids = [node["id"] for node in nodes if node["kind"] == "instructional_body"]
        adjacency = {node["id"]: set() for node in nodes}
        edge_map: dict[frozenset[str], dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        for left_index, left in enumerate(nodes):
            for right in nodes[left_index + 1 :]:
                evidence = _intra_anchor_evidence(left["value"], right["value"])
                if evidence["status"] != "passed":
                    continue
                adjacency[left["id"]].add(right["id"])
                adjacency[right["id"]].add(left["id"])
                edge = {
                    "left": left["id"],
                    "right": right["id"],
                    "left_diagnostic": _diagnostic_fragment(left["value"]),
                    "right_diagnostic": _diagnostic_fragment(right["value"]),
                    "evidence": _intra_diagnostic_evidence(evidence),
                }
                edges.append(edge)
                edge_map[frozenset((left["id"], right["id"]))] = edge

        def edge_between(left_id: str, right_id: str) -> dict[str, Any] | None:
            return edge_map.get(frozenset((left_id, right_id)))

        def component(seed: str) -> set[str]:
            members: set[str] = set()
            pending = [seed]
            while pending:
                current = pending.pop()
                if current in members:
                    continue
                members.add(current)
                pending.extend(adjacency[current] - members)
            return members

        task_component_ids = component("task")
        task_body_edges = [
            (body_id, edge_between("task", body_id))
            for body_id in body_node_ids
            if edge_between("task", body_id) is not None
        ]
        task_connected = bool(task_body_edges)
        deliverable_connected = task_connected and "deliverable" in task_component_ids
        gate_a_body = max(
            task_body_edges,
            key=lambda item: (item[1]["evidence"]["score"], item[0]),
            default=(None, None),
        )
        gate_a_body_id, gate_a_edge = gate_a_body
        gate_a_evidence = (
            gate_a_edge["evidence"]
            if gate_a_edge is not None
            else {"status": "failed", "score": 0.0, "reason": "task has no substantive edge to instructional body"}
        )
        task_anchor_edge = edge_between("deliverable", "task")
        deliverable_body_edges = [
            (body_id, edge_between("deliverable", body_id))
            for body_id in body_node_ids
            if edge_between("deliverable", body_id) is not None
        ]
        body_anchor_id, body_anchor_edge = max(
            deliverable_body_edges,
            key=lambda item: (item[1]["evidence"]["score"], item[0]),
            default=(None, None),
        )
        body_anchor_evidence = (
            body_anchor_edge["evidence"]
            if body_anchor_edge is not None
            else {"status": "failed", "score": 0.0, "reason": "deliverable has no substantive edge to instructional body"}
        )
        same_component_body_edges = [
            (body_id, edge_between("deliverable", body_id))
            for body_id in body_node_ids
            if body_id in task_component_ids and edge_between("deliverable", body_id) is not None
        ]
        cross_body_id, cross_body_edge = max(
            same_component_body_edges,
            key=lambda item: (item[1]["evidence"]["score"], item[0]),
            default=(None, None),
        )
        cross_body_anchor = (
            cross_body_edge["evidence"]
            if cross_body_edge is not None
            else {"status": "failed", "score": 0.0, "reason": "deliverable has no edge inside task component"}
        )

        def node_field(node_id: str | None) -> str | None:
            return node_by_id[node_id]["field"] if node_id is not None else None

        def node_index(node_id: str | None) -> int | None:
            return node_by_id[node_id].get("index") if node_id is not None else None

        gate_a_result = {
            "status": "passed" if task_connected else "failed",
            "score": gate_a_evidence["score"],
            "anchor_status": gate_a_evidence["status"],
            "reason": (
                "task has a substantive edge to instructional body"
                if task_connected
                else "task has no substantive edge to teaching_content/key_point.content/difficult_point.content"
            ),
            "matched_field": node_field(gate_a_body_id),
            "matched_body_index": node_index(gate_a_body_id),
            "matched_node": gate_a_body_id,
            "candidates": {
                field: {
                    "status": "passed" if any(
                        node_by_id[node_id]["field"] == field
                        for node_id, _node_edge in task_body_edges
                    ) else "failed",
                    "score": max(
                        (node_edge["evidence"]["score"] for node_id, node_edge in task_body_edges if node_by_id[node_id]["field"] == field),
                        default=0.0,
                    ),
                }
                for field in body_fields
            },
        }
        gate_b_passed = deliverable_connected
        gate_b_result = {
            "status": "passed" if gate_b_passed else "failed",
            "score": round(
                min(
                    gate_a_result["score"],
                    task_anchor_edge["evidence"]["score"] if task_anchor_edge else body_anchor_evidence["score"],
                ),
                4,
            ),
            "anchor_status": {
                "task": "passed" if task_connected else "failed",
                "body": body_anchor_evidence["status"],
                "shared_component": "passed" if gate_b_passed else "failed",
            },
            "reason": (
                "task and deliverable belong to the same main semantic component"
                if gate_b_passed
                else "deliverable belongs to a component disconnected from the task main semantic component"
            ),
            "task_anchor": task_anchor_edge["evidence"] if task_anchor_edge else {"status": "failed", "score": 0.0},
            "body_anchor": body_anchor_evidence,
            "shared_cluster": {
                "same_gate_a_body": edge_between("deliverable", gate_a_body_id) is not None if gate_a_body_id else False,
                "direct_task_and_body": task_anchor_edge is not None and body_anchor_edge is not None,
                "cross_body_bridge": cross_body_edge is not None,
                "same_component": gate_b_passed,
                "same_gate_a_body_evidence": (
                    edge_between("deliverable", gate_a_body_id)["evidence"]
                    if gate_a_body_id and edge_between("deliverable", gate_a_body_id)
                    else {"status": "failed", "score": 0.0}
                ),
                "cross_body_evidence": cross_body_anchor,
                "cross_body_gate_a_body_index": node_index(cross_body_id),
                "deliverable_matched_field": node_field(body_anchor_id),
                "deliverable_matched_body_index": node_index(body_anchor_id),
            },
        }

        progression_values = lesson.get("progression", {})
        eligible_progression: list[tuple[str, Any, str, dict[str, Any]]] = []
        if task_connected:
            for field in progression_fields:
                value = progression_values.get(field, "")
                for core_id in sorted(task_component_ids):
                    if core_id not in node_by_id:
                        continue
                    evidence = _intra_anchor_evidence(value, node_by_id[core_id]["value"])
                    if evidence["status"] == "passed":
                        eligible_progression.append((field, value, core_id, evidence))
                        break

        implementation_records: list[dict[str, Any]] = []
        implementation_failures: list[dict[str, Any]] = []
        for stage in lesson.get("implementation", []):
            stage_id = str(stage.get("id", ""))
            stage_values: list[Any] = []
            for field in IMPLEMENTATION_ITEM_FIELDS:
                stage_values.extend(_implementation_items(stage, field))
            stage_summary = "\n".join(str(value) for value in stage_values if str(value).strip())
            component_matches: list[tuple[str, dict[str, Any]]] = []
            for core_id in sorted(task_component_ids):
                evidence = _intra_anchor_evidence(stage_summary, node_by_id[core_id]["value"])
                if evidence["status"] == "passed":
                    component_matches.append((core_id, evidence))
            progression_matches: list[tuple[str, str, dict[str, Any]]] = []
            if stage_id in boundary_stage_ids:
                for field, _value, core_id, progression_evidence in eligible_progression:
                    stage_evidence = _intra_anchor_evidence(stage_summary, progression_values.get(field, ""))
                    if stage_evidence["status"] == "passed":
                        progression_matches.append((field, core_id, stage_evidence))
            item_records: list[dict[str, Any]] = []
            for field in IMPLEMENTATION_ITEM_FIELDS:
                for item_index, item in enumerate(_implementation_items(stage, field)):
                    diagnostic = _diagnostic_fragment(item)
                    if _is_generic_implementation_item(field, item):
                        item_records.append(
                            {
                                "field": field,
                                "item_index": item_index,
                                "status": "passed",
                                "reason": "generic pedagogical item exempt from substantive anchor",
                                "diagnostic": diagnostic,
                                "generic": True,
                            }
                        )
                        continue

                    item_component_matches: list[tuple[str, dict[str, Any]]] = []
                    for core_id in sorted(task_component_ids):
                        evidence = _implementation_anchor_evidence(item, node_by_id[core_id]["value"])
                        if evidence["status"] == "passed":
                            item_component_matches.append((core_id, evidence))
                    item_progression_matches: list[tuple[str, str, dict[str, Any]]] = []
                    if stage_id in boundary_stage_ids:
                        for progression_field, _value, core_id, _progression_evidence in eligible_progression:
                            item_evidence = _implementation_anchor_evidence(
                                item,
                                progression_values.get(progression_field, ""),
                            )
                            if item_evidence["status"] == "passed":
                                item_progression_matches.append((progression_field, core_id, item_evidence))
                    item_passed = bool(item_component_matches or item_progression_matches)
                    item_record = {
                        "field": field,
                        "item_index": item_index,
                        "status": "passed" if item_passed else "failed",
                        "reason": (
                            "substantive item is connected to lesson main semantic component"
                            if item_passed
                            else "substantive item is disconnected from lesson main semantic component"
                        ),
                        "diagnostic": diagnostic,
                        "generic": False,
                        "matched_component_members": [match[0] for match in item_component_matches],
                        "matched_progression_fields": [match[0] for match in item_progression_matches],
                        "evidence": [
                            {"target": target, "evidence": _intra_diagnostic_evidence(evidence)}
                            for target, evidence in item_component_matches
                        ]
                        + [
                            {
                                "target": progression_field,
                                "component_member": core_id,
                                "evidence": _intra_diagnostic_evidence(evidence),
                            }
                            for progression_field, core_id, evidence in item_progression_matches
                        ],
                    }
                    item_records.append(item_record)
                    if not item_passed:
                        implementation_failures.append(
                            {
                                "lesson_id": lesson_id,
                                "failed_gate": "implementation_item_coherence",
                                "stage": stage_id,
                                "stage_id": stage_id,
                                "field": field,
                                "item_index": item_index,
                                "status": "failed",
                                "score": 0.0,
                                "anchor_status": "failed",
                                "reason": item_record["reason"],
                                "diagnostic": diagnostic,
                            }
                        )
            stage_passed = bool(item_records) and all(item["status"] == "passed" for item in item_records)
            stage_record = {
                "stage_id": stage_id,
                "status": "passed" if stage_passed else "failed",
                "matched_component_members": [item[0] for item in component_matches],
                "matched_progression_fields": [item[0] for item in progression_matches],
                "aggregate_diagnostic": _diagnostic_fragment(stage_summary),
                "items": item_records,
                "evidence": [
                    {"target": target, "evidence": _intra_diagnostic_evidence(evidence)}
                    for target, evidence in component_matches
                ]
                + [
                    {"target": field, "component_member": core_id, "evidence": _intra_diagnostic_evidence(evidence)}
                    for field, core_id, evidence in progression_matches
                ],
            }
            implementation_records.append(stage_record)
            if not stage_passed and not any(
                failure.get("stage_id") == stage_id for failure in implementation_failures
            ):
                implementation_failures.append(
                    {
                        "lesson_id": lesson_id,
                        "failed_gate": "implementation_stage_coherence",
                        "stage": stage_id,
                        "stage_id": stage_id,
                        "field": None,
                        "item_index": None,
                        "status": "failed",
                        "score": 0.0,
                        "anchor_status": "failed",
                        "reason": "implementation stage has no substantive anchor to the task main component",
                        "diagnostic": _diagnostic_fragment(stage_summary),
                    }
                )

        main_component = {
            "task_connected": task_connected,
            "deliverable_connected": deliverable_connected,
            "members": sorted(task_component_ids),
        }
        record = {
            "lesson_id": lesson_id,
            "main_component": main_component,
            "core_nodes": [
                {
                    **{key: value for key, value in node.items() if key != "value"},
                    "diagnostic": _diagnostic_fragment(node["value"]),
                }
                for node in nodes
            ],
            "semantic_edges": edges,
            "disconnected_core_nodes": sorted(set(node_by_id) - task_component_ids),
            "gate_a": gate_a_result,
            "gate_b": gate_b_result,
            "implementation": {
                "status": "passed" if not implementation_failures else "failed",
                "stages": implementation_records,
                "rule": "each substantive implementation item must anchor to a task-component core node; generic pedagogical items are exempt and boundary items may use anchored progression",
            },
        }
        checks.append(record)
        for gate_name, gate in (("gate_a_task_body", gate_a_result), ("gate_b_deliverable_body", gate_b_result)):
            if gate["status"] != "passed":
                failures.append(
                    {
                        "lesson_id": lesson_id,
                        "failed_gate": gate_name,
                        "score": gate["score"],
                        "anchor_status": gate["anchor_status"],
                        "reason": gate["reason"],
                    }
                )
        failures.extend(implementation_failures)
    return {
        "status": "passed" if not failures else "failed",
        "lessons": checks,
        "failures": failures,
        "thresholds": {
            "minimum_substantive_anchor_chars": 3,
            "technical_acronym_allowed": True,
            "gate_a": "task must have a direct substantive edge to an instructional body node",
            "gate_b": "task and deliverable must belong to the same connected core component",
            "implementation": "each substantive stage item, including label and modality, must anchor to task component; generic pedagogical items are exempt",
        },
    }


def _intra_calibration_stage(stage_id: str, text: str) -> dict[str, Any]:
    return {
        "id": stage_id,
        "label": "任务实施",
        "modality": "小组实训",
        "content": [text],
        "teacher_actions": ["组织课堂活动"],
        "student_actions": ["完成练习"],
        "objective": "形成可复核成果",
    }


def intra_lesson_coherence_calibration() -> list[dict[str, Any]]:
    """Small cross-domain calibration corpus kept independent of user data."""

    simple_cases = (
        ("database_positive", "设计数据库表结构", ["确定主键外键并检查数据库表约束"], "数据库表设计说明", "passed"),
        ("nursing_positive", "完成患者生命体征测量", ["练习血压、体温测量并记录异常判定"], "生命体征测量记录", "passed"),
        ("accounting_positive", "整理会计凭证并登记账簿", ["审核原始凭证并按科目登记账簿"], "凭证与账簿核对表", "passed"),
        ("database_positive_explicit", "数据库表结构设计", ["数据库表的主键、外键、字段约束"], "数据库表设计说明", "passed"),
        ("nursing_positive_explicit", "患者生命体征测量", ["患者生命体征包括血压、体温、异常判定"], "生命体征测量记录", "passed"),
        ("http_positive_entity_chain", "分析 HTTP 请求过程", ["HTTP请求头、状态码、浏览器开发者工具"], "Web 请求分析报告", "passed"),
        ("nursing_task_sql_deliverable", "完成患者生命体征测量", ["编写SQL查询并验证结果"], "SQL查询脚本", "failed"),
        ("database_task_nursing_body", "设计数据库表结构", ["练习血压、体温测量并记录异常判定"], "数据库表设计说明", "failed"),
        ("accounting_task_java_deliverable", "登记会计凭证并核对账簿", ["编写Java类并运行单元测试"], "Java程序包", "failed"),
        ("nursing_sql_mixed_body", "完成患者无菌护理操作", ["无菌护理准备与患者护理操作", "使用 SQL 完成数据库查询"], "SQL 查询结果记录", "failed"),
        ("database_task_nursing_body_database_deliverable", "数据库表结构设计", ["血压、体温、异常判定"], "数据库表设计说明", "failed"),
        ("task_body_a_deliverable_body_b", "完成数据库查询", ["数据库查询语句", "测量患者血压并记录生命体征"], "生命体征测量记录", "failed"),
        ("generic_only", "完成任务并进行分析", ["开展操作、检查流程并形成成果"], "提交成果", "failed"),
        ("prior_bridge_body_cross_domain", "完成数据库查询", ["测量患者血压并记录生命体征"], "数据库查询报告", "failed"),
    )
    composed_cases = (
        (
            "case_a_three_branch_false_bridge",
            "完成患者无菌护理操作",
            ["无菌护理准备与患者护理操作", "使用 SQL 完成数据库查询", "分析 SQL 查询性能并记录执行计划"],
            "SQL 查询结果记录",
            "failed",
            [],
        ),
        (
            "case_b_reverse_three_branch_false_bridge",
            "完成数据库查询与索引维护",
            ["设计数据库表结构并准备查询数据", "执行血压测量与患者状态核对", "形成异常护理记录"],
            "患者生命体征记录",
            "failed",
            [],
        ),
        (
            "case_c_implementation_cross_domain",
            "完成患者生命体征监测",
            ["测量血压、体温并判断异常", "形成护理监测记录", "核对患者状态"],
            "生命体征监测记录",
            "failed",
            [_intra_calibration_stage("task_implementation", "使用数据库索引优化 SQL 查询")],
        ),
        (
            "case_d_implementation_reverse_domain",
            "完成数据库查询与索引维护",
            ["编写 SQL 查询语句", "核对查询结果并记录执行计划", "形成数据库查询报告"],
            "数据库查询报告",
            "failed",
            [_intra_calibration_stage("task_implementation", "测量血压、记录患者生命体征并执行无菌护理")],
        ),
        (
            "case_e_database_multi_item_positive",
            "数据库关系模式设计",
            ["根据 E-R 图完成关系模式映射", "确定主键外键", "落实表结构约束"],
            "关系模式设计表",
            "passed",
            [],
        ),
        (
            "case_f_nursing_multi_item_positive",
            "完成患者生命体征监测",
            ["测量血压、体温并记录异常判定", "比较生命体征变化", "形成护理监测记录"],
            "生命体征监测记录",
            "passed",
            [],
        ),
        (
            "case_g_accounting_multi_item_positive",
            "整理会计凭证并登记账簿",
            ["审核原始凭证并按科目登记账簿", "根据借贷方向核对金额", "编制凭证与账簿核对表"],
            "凭证与账簿核对表",
            "passed",
            [],
        ),
    )
    results: list[dict[str, Any]] = []
    for name, task, body, deliverable, expected in simple_cases:
        lesson = {
            "lesson_id": "calibration",
            "task": task,
            "teaching_content": body,
            "key_point": {"content": [body[0]]},
            "difficult_point": {"content": [body[0]]},
            "progression": {"deliverable": deliverable},
        }
        result = _intra_lesson_coherence([lesson], ["calibration"])
        results.append({"name": name, "expected": expected, "actual": result["status"]})
    for name, task, body, deliverable, expected, implementation in composed_cases:
        lesson = {
            "lesson_id": "calibration",
            "task": task,
            "teaching_content": body,
            "key_point": {"content": [body[0]]},
            "difficult_point": {"content": [body[0]]},
            "progression": {"deliverable": deliverable},
            "implementation": implementation,
        }
        result = _intra_lesson_coherence([lesson], ["calibration"])
        results.append({"name": name, "expected": expected, "actual": result["status"]})
    return results


def _progression_gates(previous: dict[str, Any], current: dict[str, Any], threshold: float) -> dict[str, Any]:
    """Keep artifact inheritance and the next-step bridge as separate gates."""

    previous_progression = previous["progression"]
    current_progression = current["progression"]
    artifact_inheritance = _progression_gate(
        [previous_progression["deliverable"], previous.get("task", "")],
        current_progression["prior_learning"],
        threshold,
    )
    # The instructional body is the required forward-transition evidence;
    # deliverable text can corroborate but cannot rescue an unrelated body.
    body_gate = _progression_gate(
        previous_progression["next_bridge"],
        [current.get("task", ""), *current.get("teaching_content", [])],
        threshold,
    )
    current_body_coherence = _intra_lesson_coherence([current], [str(current.get("lesson_id", "current"))])
    # Current-lesson coherence is a prerequisite/diagnostic only.  It cannot
    # turn a failed cross-lesson lexical or substantive-anchor gate into a
    # pass.  In particular, a coherent database lesson must not be accepted
    # after an unrelated nursing/accounting/mechanical bridge.
    body_gate = {
        **body_gate,
        "current_body_coherence": {
            "status": current_body_coherence["status"],
            "failed_lessons": [item["lesson_id"] for item in current_body_coherence["failures"]],
        },
    }
    if current_body_coherence["status"] != "passed":
        body_gate = {
            **body_gate,
            "status": "failed",
            "lexical_status": "failed_current_body_coherence",
        }
    corroborating_gate = _progression_gate(
        previous_progression["next_bridge"],
        [current.get("task", ""), *current.get("teaching_content", []), current_progression["deliverable"]],
        threshold,
    )
    forward_candidates = {
        "task_and_deliverable": body_gate,
        "teaching_content_and_deliverable": corroborating_gate,
        "instructional_body": body_gate,
        "instructional_body_with_deliverable": corroborating_gate,
    }
    selected_scope, selected_gate = max(
        {"instructional_body": body_gate}.items(),
        key=lambda item: (item[1]["status"] == "passed", item[1]["score"], item[0]),
    )
    forward_transition = {
        **selected_gate,
        "candidate_scope": selected_scope,
        "candidate_results": {
            scope: {"status": gate["status"], "score": gate["score"]}
            for scope, gate in forward_candidates.items()
        },
        "corroboration": {
            "status": corroborating_gate["status"],
            "score": corroborating_gate["score"],
            "deliverable_cannot_rescue_body": True,
        },
    }
    return {
        "artifact_inheritance": artifact_inheritance,
        "forward_transition": forward_transition,
        "status": (
            "passed"
            if artifact_inheritance["status"] == "passed" and forward_transition["status"] == "passed"
            else "failed"
        ),
    }


def _calibration_lesson(
    lesson_id: str,
    task: str,
    teaching_content: list[str],
    prior_learning: str,
    deliverable: str,
) -> dict[str, Any]:
    """Build a compact composed-gate case with an internally coherent lesson."""

    return {
        "lesson_id": lesson_id,
        "task": task,
        "teaching_content": teaching_content,
        "key_point": {"content": [teaching_content[0]]},
        "difficult_point": {"content": [teaching_content[0]]},
        "progression": {
            "prior_learning": prior_learning,
            "deliverable": deliverable,
        },
    }


PROGRESSION_GATE_CALIBRATION_CORPUS = (
    (
        "false_inheritance",
        {
            "task": "完成需求分析",
            "progression": {
                "deliverable": "数据库需求分析报告",
                "next_bridge": "根据表结构完成SQL查询",
            },
        },
        {
            "task": "完成SQL查询设计",
            "teaching_content": ["依据表结构编写查询语句", "验证查询结果"],
            "progression": {
                "prior_learning": "承接护理实训基础",
                "deliverable": "SQL查询脚本和结果记录",
            },
        },
        "failed",
        "passed",
        "failed",
    ),
    (
        "false_bridge",
        {
            "task": "完成关系模式设计",
            "progression": {
                "deliverable": "E-R图",
                "next_bridge": "根据表结构完成SQL查询",
            },
        },
        {
            "task": "设计护理床整理流程",
            "teaching_content": ["整理床单位", "检查护理操作规范"],
            "progression": {
                "prior_learning": "承接E-R图中的实体及联系",
                "deliverable": "护理床整理记录",
            },
        },
        "passed",
        "failed",
        "failed",
    ),
    (
        "connected",
        {
            "task": "完成需求分析",
            "progression": {
                "deliverable": "E-R图",
                "next_bridge": "将实体关系转换为关系表",
            },
        },
        {
            "task": "完成关系模式设计",
            "teaching_content": ["主键、外键与关系表映射", "依据E-R图确定字段"],
            "progression": {
                "prior_learning": "能解释上一课E-R图中的实体及联系",
                "deliverable": "关系模式设计表",
            },
        },
        "passed",
        "passed",
        "passed",
    ),
    (
        "functional_test_points",
        {
            "task": "设计功能测试用例",
            "progression": {
                "deliverable": "功能测试用例集",
                "next_bridge": "提取下一课的功能测试点",
            },
        },
        _calibration_lesson(
            "functional_test_points",
            "执行功能测试",
            ["按功能测试点执行边界场景", "记录预期与实际结果"],
            "承接功能测试用例集",
            "功能测试执行记录",
        ),
        "passed",
        "passed",
        "passed",
    ),
    (
        "sql_result_bridge",
        {
            "task": "完成SQL查询",
            "progression": {
                "deliverable": "SQL查询结果记录",
                "next_bridge": "根据SQL查询结果分析索引性能",
            },
        },
        _calibration_lesson(
            "sql_result_bridge",
            "分析索引性能",
            ["依据SQL查询结果比较索引性能", "记录执行计划差异"],
            "承接SQL查询结果记录",
            "索引性能分析表",
        ),
        "passed",
        "passed",
        "passed",
    ),
    (
        "nursing_artifact_bridge",
        {
            "task": "完成生命体征测量",
            "progression": {
                "deliverable": "生命体征测量记录",
                "next_bridge": "依据生命体征记录完成护理风险判断",
            },
        },
        _calibration_lesson(
            "nursing_artifact_bridge",
            "完成护理风险判断",
            ["依据生命体征记录识别异常", "形成护理风险判断单"],
            "承接生命体征测量记录",
            "护理风险判断单",
        ),
        "passed",
        "passed",
        "passed",
    ),
    (
        "generic_operation_composed",
        {
            "task": "完成护理记录",
            "progression": {
                "deliverable": "护理操作流程记录",
                "next_bridge": "护理操作流程",
            },
        },
        _calibration_lesson(
            "generic_operation_composed",
            "数据库操作与索引维护",
            ["创建索引并验证查询计划", "记录索引维护结果"],
            "承接护理操作流程记录",
            "数据库索引维护记录",
        ),
        "passed",
        "failed",
        "failed",
    ),
    (
        "generic_design_composed",
        {
            "task": "完成护理方案复核",
            "progression": {
                "deliverable": "患者风险评估与护理方案设计记录",
                "next_bridge": "患者风险评估与护理方案设计",
            },
        },
        _calibration_lesson(
            "generic_design_composed",
            "数据库索引设计",
            ["确定联合索引字段", "验证索引查询性能"],
            "承接患者风险评估与护理方案设计记录",
            "数据库索引设计表",
        ),
        "passed",
        "failed",
        "failed",
    ),
    (
        "generic_analysis_composed",
        {
            "task": "完成会计凭证整理",
            "progression": {
                "deliverable": "会计数据分析报告",
                "next_bridge": "会计数据分析",
            },
        },
        _calibration_lesson(
            "generic_analysis_composed",
            "软件缺陷分析",
            ["复现软件缺陷并定位日志异常", "记录缺陷影响范围"],
            "承接会计数据分析报告",
            "软件缺陷分析报告",
        ),
        "passed",
        "failed",
        "failed",
    ),
    (
        "generic_check_record_composed",
        {
            "task": "完成机械设备巡检",
            "progression": {
                "deliverable": "机械检查记录",
                "next_bridge": "机械检查记录",
            },
        },
        _calibration_lesson(
            "generic_check_record_composed",
            "护理检查记录",
            ["核对患者体征与护理记录", "形成护理检查记录单"],
            "承接机械检查记录",
            "护理检查记录单",
        ),
        "passed",
        "failed",
        "failed",
    ),
    (
        "generic_implementation_composed",
        {
            "task": "完成项目方案评审",
            "progression": {
                "deliverable": "项目实施方案",
                "next_bridge": "项目实施方案",
            },
        },
        _calibration_lesson(
            "generic_implementation_composed",
            "无菌护理实施",
            ["按无菌要求准备护理用品", "记录无菌操作检查结果"],
            "承接项目实施方案",
            "无菌护理实施记录",
        ),
        "passed",
        "failed",
        "failed",
    ),
    (
        "generic_flow_design_composed",
        {
            "task": "完成流程设计评审",
            "progression": {
                "deliverable": "流程设计结果",
                "next_bridge": "流程设计结果",
            },
        },
        _calibration_lesson(
            "generic_flow_design_composed",
            "Java 接口设计",
            ["定义Java接口方法并编写调用示例", "验证接口参数约束"],
            "承接流程设计结果",
            "Java接口设计说明",
        ),
        "passed",
        "failed",
        "failed",
    ),
)


def progression_gate_calibration() -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    for (
        label,
        previous,
        current,
        expected_artifact,
        expected_forward,
        expected_overall,
    ) in PROGRESSION_GATE_CALIBRATION_CORPUS:
        gates = _progression_gates(previous, current, PROGRESSION_DECLARED_BOUNDARY_THRESHOLD)
        actual = {
            "artifact_inheritance": gates["artifact_inheritance"]["status"],
            "forward_transition": gates["forward_transition"]["status"],
            "overall": gates["status"],
        }
        calibrated.append(
            {
                "case": label,
                "expected": {
                    "artifact_inheritance": expected_artifact,
                    "forward_transition": expected_forward,
                    "overall": expected_overall,
                },
                "actual": actual,
                "gates": gates,
            }
        )
    return calibrated


# This small, reviewable corpus calibrates the threshold classes.  The positive
# pairs share a concrete artifact or clinical action; the negative pairs only
# share generic teaching language and must not pass by one accidental n-gram.
PROGRESSION_CALIBRATION_CORPUS = (
    ("er_model", "E-R图", "根据 E-R 图设计关系模式", "通过"),
    ("requirements_report", "数据库需求分析报告", "承接需求分析成果设计后续结构", "通过"),
    ("vital_signs", "生命体征监测记录", "根据监测记录判断异常护理", "通过"),
    ("accounting_voucher", "会计凭证审核结果", "根据凭证审核结果登记账簿", "通过"),
    ("sql_results", "SQL查询结果", "根据 SQL 查询结果进行性能分析", "通过"),
    ("generic_operation", "护理操作流程", "数据库操作与索引维护", "失败"),
    ("generic_design", "患者风险评估与护理方案设计", "数据库索引设计", "失败"),
    ("generic_analysis", "会计数据分析", "软件缺陷分析", "失败"),
    ("generic_check_record", "机械检查记录", "护理检查记录", "失败"),
    ("generic_implementation", "项目实施方案", "无菌护理实施", "失败"),
    ("generic_flow_design", "流程设计结果", "Java 接口设计", "失败"),
)


def progression_calibration() -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    for label, upstream, downstream, expected in PROGRESSION_CALIBRATION_CORPUS:
        signals = _progression_gate(upstream, downstream, PROGRESSION_DECLARED_BOUNDARY_THRESHOLD)
        raw_score = round(float(signals["score"]), 4)
        passed = signals["status"] == "passed"
        calibrated.append(
            {
                "case": label,
                "upstream": upstream,
                "downstream": downstream,
                "expected": expected,
                "signals": signals,
                "raw_score": raw_score,
                "passed": passed,
                "effective_status": "passed" if passed else "failed",
                # Compatibility alias; keep the raw score for failed cases
                # so calibration margins describe the actual classifier.
                "evidence_score": raw_score,
                "calibrated_status": "通过" if signals["status"] == "passed" else "失败",
            }
        )
    return calibrated


def progression_calibration_margin() -> dict[str, Any]:
    cases = progression_calibration()
    positives = [item["raw_score"] for item in cases if item["expected"] == "通过"]
    negatives = [item["raw_score"] for item in cases if item["expected"] == "失败"]
    positive_minimum = min(positives) if positives else 0.0
    negative_maximum = max(negatives) if negatives else 0.0
    return {
        "positive_minimum": round(positive_minimum, 4),
        "negative_maximum": round(negative_maximum, 4),
        "margin": round(positive_minimum - negative_maximum, 4),
        "positive_count": len(positives),
        "hard_negative_count": len(negatives),
    }


def _score_pattern(scores: list[float], errors: list[str]) -> dict[str, Any]:
    score_pattern: dict[str, Any] = {
        "values": scores,
        "all_same": len(scores) > 1 and len(set(scores)) == 1,
        "simple_cycle": False,
        "cycle_period": None,
        "cycle_confidence": 0.0,
        "full_cycles": 0,
        "tail_length": 0,
        "tail_fraction": 0.0,
        "arithmetic_progression": False,
        "arithmetic_step": None,
        "strict_monotonic": False,
        "range_valid": True,
    }
    for value in scores:
        if value < float(EVALUATION_SCORE_MIN) or value > float(EVALUATION_SCORE_MAX) or (value * 2) % 1:
            score_pattern["range_valid"] = False
            errors.append(f"evaluation score {value} is outside 85-96 half-point contract")
    # A partial tail is only mechanical when it repeats a substantial portion
    # of the initial period. Two coincidental values at the end of a long,
    # otherwise natural sequence are not sufficient evidence.
    for period in range(1, len(scores) - 1):
        repeated = all(scores[index] == scores[index % period] for index in range(period, len(scores)))
        full_cycles, tail_length = divmod(len(scores), period)
        complete_cycle = full_cycles >= 2 and repeated
        minimum_tail = max(3, (period + 1) // 2)
        partial_tail_cycle = full_cycles == 1 and tail_length >= minimum_tail and repeated
        if complete_cycle or partial_tail_cycle:
            score_pattern["simple_cycle"] = True
            score_pattern["cycle_period"] = period
            score_pattern["full_cycles"] = full_cycles
            score_pattern["tail_length"] = tail_length
            score_pattern["tail_fraction"] = round(tail_length / period, 4) if period else 0.0
            score_pattern["cycle_confidence"] = (
                1.0 if complete_cycle else round(tail_length / period, 4)
            )
            break
    if len(scores) >= 4:
        steps = [round(scores[index + 1] - scores[index], 6) for index in range(len(scores) - 1)]
        if steps and steps[0] != 0 and all(step == steps[0] for step in steps):
            score_pattern["arithmetic_progression"] = True
            score_pattern["arithmetic_step"] = steps[0]
    if score_pattern["all_same"]:
        errors.append("evaluation scores are identical across lessons")
    if score_pattern["simple_cycle"]:
        errors.append("evaluation scores use a simple repeating cycle")
    if score_pattern["arithmetic_progression"]:
        errors.append("evaluation scores use a mechanical arithmetic progression")
    if len(scores) >= 4:
        steps = [scores[index + 1] - scores[index] for index in range(len(scores) - 1)]
        if all(step > 0 for step in steps) or all(step < 0 for step in steps):
            score_pattern["strict_monotonic"] = True
            errors.append("evaluation scores use a strict monotonic sequence")
    return score_pattern


def _reference_provenance_report(lessons: list[dict[str, Any]], lesson_ids: list[str]) -> dict[str, Any]:
    by_lesson: dict[str, list[dict[str, Any]]] = {}
    missing_evidence: list[dict[str, Any]] = []
    invalid_generic: list[dict[str, Any]] = []
    invalid_verified_public: list[dict[str, Any]] = []
    for lesson_id, lesson in zip(lesson_ids, lessons):
        entries: list[dict[str, Any]] = []
        for index, reference in enumerate(lesson.get("references", []), 1):
            text = _normalize(reference.get("text", ""))
            source_kind = str(reference.get("source_kind", ""))
            evidence = reference.get("evidence")
            evidence_present = _meaningful_length(evidence or "") > 0
            entry = {
                "index": index,
                "source_kind": source_kind,
                "evidence_present": evidence_present,
            }
            entries.append(entry)
            if source_kind in {"provided", "verified_public"} and not evidence_present:
                missing_evidence.append(
                    {"lesson": lesson_id, "reference": index, "source_kind": source_kind}
                )
            if source_kind == "verified_public" and evidence_present:
                evidence_text = _normalize(evidence)
                if not (
                    REFERENCE_EVIDENCE_URL_PATTERN.search(evidence_text)
                    or REFERENCE_EVIDENCE_LOCATOR_PATTERN.search(evidence_text)
                ):
                    invalid_verified_public.append(
                        {"lesson": lesson_id, "reference": index}
                    )
            if source_kind == "generic" and (
                REFERENCE_SPECIFIC_PATTERN.search(text)
                or re.search(r"《[^》]{2,}》", text)
                or re.search(r"(?:isbn|gb\s*[/-]?\s*t|出版社|作者|标准编号|文件编号|版次)", text, re.IGNORECASE)
            ):
                invalid_generic.append({"lesson": lesson_id, "reference": index})
        by_lesson[lesson_id] = entries
    return {
        "by_lesson": by_lesson,
        "validation_scope": "contract_and_locator_only",
        "missing_evidence": missing_evidence,
        "invalid_generic": invalid_generic,
        "invalid_verified_public": invalid_verified_public,
    }


def assess_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run deterministic course-level checks, including item and skeleton repetition."""

    lessons = data.get("lessons", [])
    lesson_ids = [_lesson_id(lesson, index) for index, lesson in enumerate(lessons, 1)]
    lessons_by_id = dict(zip(lesson_ids, lessons))
    errors: list[str] = []
    warnings: list[str] = []
    course_terms = _course_terms(lessons)
    intra_lesson_coherence = _intra_lesson_coherence(lessons, lesson_ids)
    intra_lesson_coherence["calibration"] = intra_lesson_coherence_calibration()
    if intra_lesson_coherence["status"] != "passed":
        errors.extend(
            f"intra_lesson_coherence {item['lesson_id']} {item['failed_gate']}: {item['reason']}"
            for item in intra_lesson_coherence["failures"]
        )

    duplicate_values: dict[str, dict[str, str]] = {}
    item_values: dict[str, dict[str, list[str]]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, value in _field_groups(lesson).items():
            duplicate_values.setdefault(field, {})[lesson_id] = value
        for field, values in _item_values(lesson).items():
            item_values.setdefault(field, {})[lesson_id] = values

    exact_duplicates = _record_duplicate_groups(duplicate_values)
    adjacent_exact_duplicates = _adjacent_exact_duplicates(duplicate_values, lesson_ids)
    item_duplicates, adjacent_item_duplicates, frequency_item_duplicates = _item_duplicate_reports(
        item_values,
        lesson_ids,
        course_terms,
    )

    def allowed(field: str, text: str) -> bool:
        return _is_allowed_repeated_item(field, text, course_terms)

    for item in exact_duplicates:
        if not allowed(item["field"], item["text"]):
            errors.append(f"exact duplicate {item['field']}: {','.join(item['lessons'])}")
    for item in adjacent_exact_duplicates:
        if not allowed(item["field"], item.get("text", "")):
            errors.append(f"adjacent exact duplicate {item['field']} {item['lessons']}")
    reported_item_errors: set[tuple[str, tuple[str, ...], str]] = set()
    for item in (*adjacent_item_duplicates, *frequency_item_duplicates):
        key = (item["field"], tuple(item["lessons"]), item["normalized"])
        if key in reported_item_errors:
            continue
        reported_item_errors.add(key)
        reason = "adjacent" if item in adjacent_item_duplicates else "frequency"
        errors.append(f"{reason} repeated item {item['field']}: {','.join(item['lessons'])}")

    implementation_values: dict[str, dict[str, str]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for stage in lesson.get("implementation", []):
            stage_id = str(stage.get("id", ""))
            formatted = format_implementation_stage(stage)
            for field_name, cell_index in zip(IMPLEMENTATION_STAGE_FIELDS, (1, 2, 3, 4)):
                implementation_values.setdefault(f"{stage_id}.{field_name}", {})[lesson_id] = formatted[cell_index]
    implementation_duplicates = _record_duplicate_groups(
        implementation_values,
        IMPLEMENTATION_DUPLICATE_LESSON_COUNT,
    )
    adjacent_implementation_exact_duplicates = _adjacent_exact_duplicates(implementation_values, lesson_ids)
    for record in adjacent_implementation_exact_duplicates:
        record["stage"] = record["field"].split(".", 1)[0]
    if implementation_duplicates:
        errors.extend(
            f"implementation duplicate {item['field']}: {','.join(item['lessons'])}"
            for item in implementation_duplicates
        )

    similarity_values = {
        field: values
        for field, values in duplicate_values.items()
        if reuse_policy(field) == REUSE_NARRATIVE_STRICT
    }
    field_similarity_pairs, adjacent_field_similarity_pairs = _pairwise_similarity(
        similarity_values,
        lesson_ids,
        threshold=FIELD_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_FIELD_SIMILARITY_THRESHOLD,
    )
    for item in field_similarity_pairs:
        if not allowed(item["field"], duplicate_values[item["field"]][item["lessons"][0]]):
            errors.append(f"high field similarity {item['field']} {item['lessons']}: {item['score']}")

    implementation_similarity_pairs, adjacent_implementation_similarity_pairs = _pairwise_similarity(
        implementation_values,
        lesson_ids,
        threshold=IMPLEMENTATION_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD,
        implementation=True,
    )
    implementation_similarity_pairs = adjacent_implementation_exact_duplicates + implementation_similarity_pairs
    adjacent_implementation_similarity_pairs = (
        adjacent_implementation_exact_duplicates + adjacent_implementation_similarity_pairs
    )
    implementation_similarity_pairs.sort(
        key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"])
    )
    adjacent_implementation_similarity_pairs.sort(
        key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"])
    )
    if implementation_similarity_pairs:
        errors.extend(
            f"high implementation similarity {item.get('stage', item.get('field'))} {item['lessons']}: {item['score']}"
            for item in implementation_similarity_pairs
        )

    remark_values = {
        field: values
        for field, values in duplicate_values.items()
        if field.startswith("evaluation.remarks.")
    }
    evaluation_remark_duplicates = [
        item for item in item_duplicates if item["field"].startswith("evaluation.remarks.")
    ]
    evaluation_remark_similarity, _adjacent_remark_similarity = _pairwise_similarity(
        remark_values,
        lesson_ids,
        threshold=0.82,
        adjacent_threshold=0.78,
    )
    for item in evaluation_remark_similarity:
        criterion = item["field"].rsplit(".", 1)[-1]
        if criterion in EVALUATION_REMARK_FIXED_CRITERIA:
            warnings.append(
                f"evaluation remark similarity is expected for {criterion}: {','.join(item['lessons'])}"
            )
        else:
            errors.append(f"high evaluation remark similarity {item['field']} {item['lessons']}: {item['score']}")
    for item in evaluation_remark_duplicates:
        criterion = item["field"].rsplit(".", 1)[-1]
        if criterion in EVALUATION_REMARK_FIXED_CRITERIA and item["count"] >= 4:
            warnings.append(f"evaluation remark {criterion} repeats across {item['count']} lessons")

    resource_values = {
        "resources": {
            lesson_id: _joined(lesson.get("resources", []))
            for lesson_id, lesson in zip(lesson_ids, lessons)
        }
    }
    resource_reuse = _record_duplicate_groups(resource_values)
    if len(lessons) >= 4 and resource_reuse and len(resource_reuse[0]["lessons"]) == len(lessons):
        warnings.append("all lessons reuse the same complete resources list")

    structural_pairs = _structural_item_pairs(
        {
            field: values
            for field, values in item_values.items()
            if not field.startswith("implementation.")
            and not field.startswith("progression.")
            and reuse_policy(field) == REUSE_NARRATIVE_STRICT
        },
        lesson_ids,
        lessons_by_id,
        threshold=STRUCTURAL_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD,
    )
    implementation_structural_pairs = _structural_item_pairs(
        {
            field: values
            for field, values in item_values.items()
            if field.startswith("implementation.")
        },
        lesson_ids,
        lessons_by_id,
        threshold=IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
    )
    if structural_pairs:
        errors.extend(
            f"structural similarity {item['field']} {item['lessons']}: masked_score={item['masked_score']}"
            for item in structural_pairs
        )
    if implementation_structural_pairs:
        errors.extend(
            f"implementation structural similarity {item['stage']} {item['lessons']}: masked_score={item['masked_score']}"
            for item in implementation_structural_pairs
        )

    sentence_locations: dict[str, dict[str, set[str]]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, values in _all_content_strings(lesson).items():
            for value in values:
                for sentence in _sentences(value):
                    sentence_locations.setdefault(sentence, {}).setdefault(lesson_id, set()).add(field)
    repeated_sentences: list[dict[str, Any]] = []
    for sentence, locations in sentence_locations.items():
        ordered_locations = [lesson_id for lesson_id in lesson_ids if lesson_id in locations]
        adjacent = any(
            _is_adjacent(lesson_ids.index(left_id), lesson_ids.index(right_id))
            for left_id, right_id in zip(ordered_locations, ordered_locations[1:])
        )
        strict_locations = {
            lesson_id: sorted(
                field for field in fields if reuse_policy(field) == REUSE_NARRATIVE_STRICT
            )
            for lesson_id, fields in locations.items()
        }
        strict_locations = {
            lesson_id: fields for lesson_id, fields in strict_locations.items() if fields
        }
        strict_ordered = [lesson_id for lesson_id in lesson_ids if lesson_id in strict_locations]
        strict_adjacent = any(
            _is_adjacent(lesson_ids.index(left_id), lesson_ids.index(right_id))
            for left_id, right_id in zip(strict_ordered, strict_ordered[1:])
        )
        if len(strict_locations) >= REPEATED_SENTENCE_LESSON_COUNT or strict_adjacent:
            diagnostic = _diagnostic_fragment(sentence)
            repeated_sentences.append(
                {
                    "sentence": diagnostic["preview"],
                    "sentence_sha256": diagnostic["text_sha256"],
                    "lessons": strict_ordered,
                    "count": len(strict_locations),
                    "fields": strict_locations,
                    "adjacent": strict_adjacent,
                    "reuse_policy": REUSE_NARRATIVE_STRICT,
                    "score": 1.0,
                    "top_fragments": [diagnostic["preview"]],
                    "top_fragment_sha256": [diagnostic["text_sha256"]],
                }
            )
    repeated_sentences.sort(key=lambda item: (-item["count"], item["sentence"]))
    if repeated_sentences:
        errors.extend(
            f"repeated sentence across lessons: {item['sentence']} (sha256={item['sentence_sha256']})"
            for item in repeated_sentences
        )

    boilerplate_hits: list[dict[str, str]] = []
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, values in _all_content_strings(lesson).items():
            text = "\n".join(values)
            for pattern in BOILERPLATE_PATTERNS:
                if pattern in text:
                    boilerplate_hits.append({"lesson": lesson_id, "field": field, "fragment": pattern})
    boilerplate_hits.sort(key=lambda item: (item["lesson"], item["field"], item["fragment"]))
    if boilerplate_hits:
        errors.extend(
            f"legacy boilerplate in {item['lesson']}.{item['field']}: {item['fragment']}"
            for item in boilerplate_hits
        )

    narratives = {_lesson_id(lesson, index): _lesson_narrative(lesson) for index, lesson in enumerate(lessons, 1)}
    whole_lesson_similarity_pairs: list[dict[str, Any]] = []
    adjacent_similarity_pairs: list[dict[str, Any]] = []
    for left_index, left_id in enumerate(lesson_ids):
        for right_id in lesson_ids[left_index + 1 :]:
            left_text, right_text = narratives[left_id], narratives[right_id]
            if min(len(left_text), len(right_text)) < 30:
                continue
            adjacent = _is_adjacent(left_index, lesson_ids.index(right_id))
            threshold = ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD if adjacent else WHOLE_LESSON_SIMILARITY_THRESHOLD
            sequence, jaccard = _similarity(left_text, right_text)
            if _similarity_exceeds(sequence, jaccard, threshold):
                record = _similarity_record(
                    left_id=left_id,
                    right_id=right_id,
                    left_text=left_text,
                    right_text=right_text,
                    sequence=sequence,
                    jaccard=jaccard,
                    adjacent=adjacent,
                )
                whole_lesson_similarity_pairs.append(record)
                if adjacent:
                    adjacent_similarity_pairs.append(record)
    whole_lesson_similarity_pairs.sort(key=lambda item: (-item["score"], item["lessons"]))
    adjacent_similarity_pairs.sort(key=lambda item: (-item["score"], item["lessons"]))
    if whole_lesson_similarity_pairs:
        errors.extend(f"high whole-lesson similarity {item['lessons']}: {item['score']}" for item in whole_lesson_similarity_pairs)

    progression_stages = [str(lesson.get("progression", {}).get("capability_stage", "")) for lesson in lessons]
    declared_prior_links: list[dict[str, Any]] = []
    sequence_links: list[dict[str, Any]] = []
    prior_ids: set[str] = set()
    for index, lesson in enumerate(lessons):
        current_id = lesson_ids[index]
        progression_data = lesson.get("progression", {})
        declared_prior = progression_data.get("prior_lesson_id")
        if index == 0:
            if declared_prior is not None:
                errors.append("lessons[0].progression.prior_lesson_id must be null")
        elif declared_prior not in prior_ids:
            errors.append(f"{current_id}.progression.prior_lesson_id must reference an earlier lesson")
        elif declared_prior != current_id:
            prior_lesson = lessons_by_id[str(declared_prior)]
            same_unit = str(prior_lesson.get("unit", "")) == str(lesson.get("unit", ""))
            threshold = PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD if same_unit else PROGRESSION_DECLARED_BOUNDARY_THRESHOLD
            gates = _progression_gates(prior_lesson, lesson, threshold)
            artifact = gates["artifact_inheritance"]
            forward = gates["forward_transition"]
            link = {
                "from": str(declared_prior),
                "to": current_id,
                "kind": "declared_prior",
                "score": round(min(artifact["score"], forward["score"]), 4),
                "sequence_matcher": round(min(artifact["sequence_matcher"], forward["sequence_matcher"]), 4),
                "character_2gram_jaccard": round(min(artifact["character_2gram_jaccard"], forward["character_2gram_jaccard"]), 4),
                "character_3gram_jaccard": round(min(artifact["character_3gram_jaccard"], forward["character_3gram_jaccard"]), 4),
                "signal_count": min(artifact["signal_count"], forward["signal_count"]),
                "threshold": threshold,
                "same_unit": same_unit,
                "status": gates["status"],
                "top_overlap": sorted(set(artifact["top_overlap"] + forward["top_overlap"]))[:5],
                "artifact_inheritance": artifact,
                "forward_transition": forward,
                "substantive_anchor": {
                    "artifact_inheritance": artifact["substantive_anchor"],
                    "forward_transition": forward["substantive_anchor"],
                },
            }
            declared_prior_links.append(link)
            if link["status"] == "failed":
                errors.append(
                    f"progression declared prior gate failed {link['from']}->{link['to']}: "
                    f"score={link['score']} threshold={threshold}"
                )
        if index > 0:
            previous_id = lesson_ids[index - 1]
            previous = lessons_by_id[previous_id]
            same_unit = str(previous.get("unit", "")) == str(lesson.get("unit", ""))
            signal = _progression_gate(
                previous["progression"]["next_bridge"],
                [lesson.get("task", ""), *lesson.get("teaching_content", [])],
                PROGRESSION_SEQUENCE_THRESHOLD,
            )
            current_body_coherence = _intra_lesson_coherence([lesson], [current_id])
            signal = {
                **signal,
                "current_body_coherence": {
                    "status": current_body_coherence["status"],
                    "failed_lessons": [item["lesson_id"] for item in current_body_coherence["failures"]],
                },
            }
            if current_body_coherence["status"] != "passed":
                signal = {**signal, "status": "failed", "lexical_status": "failed_current_body_coherence"}
            status = "passed" if signal["status"] == "passed" else "review"
            hard_failure = status == "review" and declared_prior in {None, previous_id}
            link = {
                "from": previous_id,
                "to": current_id,
                "kind": "sequence",
                "score": round(signal["score"], 4),
                "sequence_matcher": round(signal["sequence_matcher"], 4),
                "character_2gram_jaccard": round(signal["character_2gram_jaccard"], 4),
                "character_3gram_jaccard": round(signal["character_3gram_jaccard"], 4),
                "signal_count": signal["signal_count"],
                "threshold": PROGRESSION_SEQUENCE_THRESHOLD,
                "same_unit": same_unit,
                "status": "failed" if hard_failure else status,
                "hard_failure": hard_failure,
                "top_overlap": signal["top_overlap"],
                "forward_transition": signal,
                "substantive_anchor": signal["substantive_anchor"],
            }
            sequence_links.append(link)
            if hard_failure:
                errors.append(
                    f"progression sequence coherence failed {link['from']}->{link['to']}: "
                    f"score={link['score']} threshold={PROGRESSION_SEQUENCE_THRESHOLD}"
                )
        prior_ids.add(current_id)
    progression_variety = len(set(progression_stages)) > 1 if len(progression_stages) >= 4 else True
    if not progression_variety:
        errors.append("progression capability_stage is identical across all lessons")
    review_items = [
        {
            "from": item["from"],
            "to": item["to"],
            "reason": item["forward_transition"]["substantive_anchor"]["reason"]
            if item["forward_transition"]["substantive_anchor"]["status"] == "failed"
            else "physical sequence lexical coherence requires Agent confirmation",
            "score": item["score"],
            "declared_prior": lessons_by_id[item["to"]]["progression"].get("prior_lesson_id"),
        }
        for item in sequence_links
        if item["status"] == "review"
    ]
    progression = {
        "status": "passed"
        if progression_variety
        and all(item["status"] == "passed" for item in declared_prior_links)
        and not any(item["hard_failure"] for item in sequence_links)
        else "failed",
        "lesson_ids": lesson_ids,
        "capability_stages": progression_stages,
        "distinct_capability_stages": sorted(set(progression_stages)),
        "stage_count": len(progression_stages),
        "valid_variety": progression_variety,
        "links": declared_prior_links or sequence_links,
        "declared_prior_links": declared_prior_links,
        "sequence_links": sequence_links,
        "requires_agent_review": bool(review_items),
        "agent_review_items": review_items,
        "calibration": {
            "cases": progression_calibration(),
            "margin": progression_calibration_margin(),
        },
        "thresholds": {
            "declared_same_unit": PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD,
            "declared_project_boundary": PROGRESSION_DECLARED_BOUNDARY_THRESHOLD,
            "sequence": PROGRESSION_SEQUENCE_THRESHOLD,
            "minimum_signal_count": 2,
        },
    }

    scores: list[float] = []
    for lesson in lessons:
        try:
            scores.append(float(lesson["evaluation"]["score"]))
        except (KeyError, TypeError, ValueError):
            pass
    score_pattern = _score_pattern(scores, errors)

    completeness, completeness_errors = _completeness_report(data)
    errors.extend(completeness_errors)
    density_errors, meaningful_chars = _density_report(data, manifest)
    if density_errors:
        density_messages = [
            f"content density exceeds {item['field']} for {item['lesson']}: "
            f"actual_chars={item.get('actual_chars', '?')} limit={item.get('limit', '?')}"
            for item in density_errors
        ]
        # Surface a deterministic, pre-generation capacity failure before
        # secondary coherence diagnostics for the same malformed payload.
        errors = density_messages + errors

    reference_provenance = _reference_provenance_report(lessons, lesson_ids)
    for item in reference_provenance["missing_evidence"]:
        errors.append(
            f"{item['lesson']}.references[{item['reference']}].{item['source_kind']} requires evidence"
        )
    for item in reference_provenance["invalid_generic"]:
        errors.append(f"{item['lesson']}.references[{item['reference']}] generic source is too specific")
    for item in reference_provenance["invalid_verified_public"]:
        errors.append(
            f"{item['lesson']}.references[{item['reference']}] verified_public evidence is not locatable"
        )

    coverage = {
        "lesson_count": len(lessons),
        "implementation_stages": {lesson_id: len(lesson.get("implementation", [])) for lesson_id, lesson in zip(lesson_ids, lessons)},
        "meaningful_characters": meaningful_chars,
        "content_fields": len(CONTENT_FIELD_NAMES),
        "evaluation_criteria": len(EVALUATION_CRITERIA),
        "evaluation_remark_contract_limit": CONTENT_V2_EVALUATION_REMARK_MAX_CHARS,
        "in_class_stage_ids": sorted(IN_CLASS_STAGE_IDS),
        "required_stage_ids": list(IMPLEMENTATION_STAGE_IDS),
        "score_pattern": score_pattern,
        "intra_lesson_coherence": {
            "status": intra_lesson_coherence["status"],
            "failed_lessons": [item["lesson_id"] for item in intra_lesson_coherence["failures"]],
        },
        "capability_stage_vocabulary": list(CAPABILITY_STAGES),
        "completeness": completeness,
        "non_it_contamination_terms": list(NON_IT_CONTAMINATION_TERMS),
        "non_it_contamination_scope": NON_IT_CONTAMINATION_SCOPE,
        "similarity_thresholds": {
            "whole_lesson": WHOLE_LESSON_SIMILARITY_THRESHOLD,
            "adjacent_whole_lesson": ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD,
            "field": FIELD_SIMILARITY_THRESHOLD,
            "adjacent_field": ADJACENT_FIELD_SIMILARITY_THRESHOLD,
            "implementation": IMPLEMENTATION_SIMILARITY_THRESHOLD,
            "adjacent_implementation": ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD,
            "structural": STRUCTURAL_SIMILARITY_THRESHOLD,
            "adjacent_structural": ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD,
            "implementation_structural": IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
            "adjacent_implementation_structural": ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
        },
    }
    return {
        "status": "failed" if errors else "passed",
        "diagnostic_content_policy": {
            "mode": "limited_fragments",
            "max_preview_chars": DIAGNOSTIC_PREVIEW_MAX_CHARS,
            "hash": "sha256",
        },
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "reuse_policy": {
            "classes": {
                "narrative_strict": REUSE_NARRATIVE_STRICT,
                "teaching_methods": REUSE_TERMINOLOGY,
                "resources": REUSE_RESOURCE,
                "references": REUSE_REFERENCE,
                "fixed_rubric": REUSE_FIXED_RUBRIC,
                "metadata": REUSE_IGNORE,
            },
            "fixed_rubric_criteria": sorted(EVALUATION_REMARK_FIXED_CRITERIA),
            "allowed_reuse": [item for item in item_duplicates if item["allowed"]],
        },
        "exact_duplicates": exact_duplicates,
        "adjacent_exact_duplicates": adjacent_exact_duplicates,
        "item_duplicates": item_duplicates,
        "adjacent_item_duplicates": adjacent_item_duplicates,
        "frequency_item_duplicates": frequency_item_duplicates,
        "adjacent_similarity_pairs": adjacent_similarity_pairs,
        "field_similarity_pairs": field_similarity_pairs,
        "adjacent_field_similarity_pairs": adjacent_field_similarity_pairs,
        "whole_lesson_similarity_pairs": whole_lesson_similarity_pairs,
        "high_similarity_pairs": whole_lesson_similarity_pairs,
        "implementation_duplicates": implementation_duplicates,
        "adjacent_implementation_exact_duplicates": adjacent_implementation_exact_duplicates,
        "implementation_similarity_pairs": implementation_similarity_pairs,
        "adjacent_implementation_similarity_pairs": adjacent_implementation_similarity_pairs,
        "structural_similarity_pairs": structural_pairs,
        "implementation_structural_similarity_pairs": implementation_structural_pairs,
        "evaluation_remark_duplicates": evaluation_remark_duplicates,
        "evaluation_remark_similarity": evaluation_remark_similarity,
        "repeated_sentences": repeated_sentences,
        "boilerplate_hits": boilerplate_hits,
        "progression": progression,
        "intra_lesson_coherence": intra_lesson_coherence,
        "reference_provenance": reference_provenance,
        "coverage": coverage,
        "completeness": completeness,
        "density_errors": density_errors,
        "resource_reuse": resource_reuse,
        "evaluation_remark_density": [
            item for item in density_errors if str(item.get("field", "")).startswith("evaluation.remarks.")
        ],
    }


def validate_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    report = assess_content_quality(data, manifest)
    if report["status"] != "passed":
        details = "; ".join(report["errors"][:8])
        raise ContentQualityError(f"Content quality validation failed: {details}", report)
    return report


def detect_non_it_contamination(
    course_metadata: dict[str, Any],
    lesson: dict[str, Any] | str,
    rendered_text: str | None = None,
) -> list[str]:
    """Find IT defaults absent from the course metadata and current lesson source.

    The two-argument form remains accepted for callers that only have a complete
    source object; output validation uses the lesson-scoped three-argument form.
    """

    if rendered_text is None:
        rendered_text = str(lesson)
        lesson_scope: dict[str, Any] = {}
    else:
        lesson_scope = lesson if isinstance(lesson, dict) else {}
    source_text = json.dumps(
        {"course": course_metadata, "lesson": lesson_scope},
        ensure_ascii=False,
        sort_keys=True,
    )
    return sorted(
        term
        for term in NON_IT_CONTAMINATION_TERMS
        if term not in source_text and term in rendered_text
    )


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
