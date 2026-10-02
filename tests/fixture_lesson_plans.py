"""Authored synthetic Lesson prose, selected by plan identity rather than index.

These are representative test lessons, not independent curriculum Source Truth.
Task/output allocation comes from DB_SPECS. Keep instructional detail separate
from the generic acceptance builder's ordinal database-oriented sentence table.

RQ-03B corrects the old L05 focus "树形结构表示" to the already-planned
stack/queue algorithms and L06 "树的遍历" to boundary/error validation.
Neither old topic was required by that row's task/output. Neighbor L07's old
"图结构建模" focus likewise preceded its actual tree-node-model task. The
associated prior_learning/next_bridge snapshots are explicitly re-frozen after
Owner authorization; existing task, output, lesson count and hours are retained.
These plans are authored for instructional consistency, before applying any
candidate validator threshold. Their nine stages retain realistic teaching
steps and observable output rather than repeating an anchor-only sentence.
"""

from __future__ import annotations

import copy


# Each stage: content, teacher action, student evidence, design objective.
STACK_QUEUE = {
    "task": "实现栈队列的典型算法",
    "focus": "栈队列算法",
    "artifact": "算法实现记录",
    "teaching_content": [
        "依据上一课的操作接口，比较栈的后进先出与队列的先进先出顺序，先用一组数据推演入栈、出栈、入队和出队后的状态。明确操作前后的元素位置，再将推演结果作为算法实现的参照。",
        "分别实现栈队列的典型算法：按接口约定编排插入、移除和读取操作，跟踪栈顶与队首队尾的变化。将输入序列、关键状态和实际输出写入算法实现记录，逐步比对手工推演，定位顺序错误。",
        "比较同一组数据经栈和队列处理后的输出次序，解释选择不同结构的理由。交换操作序列复现实现过程，整理尚未覆盖的边界条件，随算法实现记录交给下一课进行异常处理验证。",
    ],
    "key_point": {
        "content": ["栈和队列的操作次序必须与接口约定一致：栈顶位置随入栈和出栈更新，队首队尾随入队和出队更新；用状态变化说明典型算法如何得到预期输出。"],
        "strategy": ["并列展示栈队列状态表与操作实现，先预测下一状态，再执行并解释差异，避免只凭最终输出判断算法正确性。"],
    },
    "difficult_point": {
        "content": ["将栈队列接口约定转成可执行算法时，要保持连续操作之间的状态一致；区分被读取的元素和被移除的元素，追踪位置变化造成的输出偏差，并记录修订依据。"],
        "strategy": ["把连续操作拆成单步推演，每步记录栈顶或队首队尾，拿算法实现记录逐项对照手工状态表，找到首次偏离的位置后重新运行。"],
    },
    "goals": {
        "knowledge": ["说明栈队列操作顺序、接口约定与状态变化的关系。", "解释典型算法实现记录中的输入、状态和输出如何对应。"],
        "ability": ["依据既有接口实现栈队列的典型算法并复现连续操作。", "将手工推演与实际输出比较，修订顺序错误并提交算法实现记录。"],
        "quality": ["先说明预期结果，再执行操作，保留能够复查的过程证据。", "在栈队列算法互审中依据状态记录讨论差异，不以运行结束代替正确性判断。"],
    },
    "student_analysis": {
        "base": ["已完成栈队列接口设计，能够说出插入、移除和读取操作的输入输出。", "能够用顺序表或链表表示线性数据，需要将表示方法用于操作实现。"],
        "problems": ["容易只比较最终输出，遗漏连续操作中的位置变化。", "可能混淆读取与移除，导致后续操作使用错误状态。"],
        "strategies": ["先手工推演栈队列状态，再比较运行记录，按首次差异定位问题。", "以接口设计记录检查算法输入输出约定，并交换序列进行复现。"],
    },
    "stages": [
        ("预读栈队列接口设计记录，准备一组包含插入、读取和移除的操作序列。", "检查接口中的输入输出约定，提示学生先写预期状态。", "提交栈队列操作序列及手工预测结果，标出尚不清楚的约定。", "将接口设计成果转成算法实现的准备条件。"),
        ("对同一组数据分别按栈和队列次序处理，比较两种输出。", "展示栈队列顺序差异，追问哪次操作使状态分开。", "绘制栈顶和队首队尾变化，解释输出次序的不同。", "把结构规则与典型算法需要保持的状态联系起来。"),
        ("依据栈队列接口示范单步算法，逐次展示位置更新与返回值。", "并列呈现栈队列状态表和实现步骤，说明读取与移除的区别。", "在算法实现记录中写入操作前状态、操作后状态与实际返回值。", "掌握由接口约定推导算法步骤的方法。"),
        ("分组实现栈队列的插入、移除和读取操作，执行连续操作序列。", "检查栈队列算法的状态衔接，让学生定位首次偏离预期的位置。", "提交栈队列算法及运行记录，标出一处差异和修订原因。", "形成能够对照手工推演的算法实现证据。"),
        ("改变栈队列输入顺序，比较输出变化是否符合结构规则。", "追问栈队列算法在不同序列下保持不变的操作约定。", "补充两组栈队列输出对照，解释算法是否保持操作次序。", "检验算法在序列变化时仍满足接口约定。"),
        ("按既有接口整理栈队列算法实现记录，复现完整操作过程。", "核查算法实现记录是否同时保留输入、状态变化与输出。", "提交可复现的算法实现记录和实现文件，列出待验证条件。", "完成供下一课边界与异常验证使用的实现交付。"),
        ("交换栈队列操作序列和实现记录，开展独立复现。", "要求互评者依据栈队列状态记录指出具体差异。", "写出栈队列算法互评意见及对应操作位置，反馈修订建议。", "依据可观察的状态变化校核典型算法。"),
        ("归纳栈队列算法从接口、状态推演到运行对照的实现路径。", "对比栈队列操作规则，确认尚待下一课检查的边界条件。", "说明栈队列实现中的一个关键决定，并列出下一课的验证问题。", "巩固算法实现方法并明确验证环节的输入。"),
        ("依据互评意见修订栈队列算法，保留前后状态记录。", "反馈栈队列算法修订是否解决首次状态偏差。", "上传栈队列修订实现、复现记录和待验证条件清单。", "为后续边界与异常验证提供稳定的算法版本。"),
    ],
    "assessment_signal": "根据状态表复现栈队列操作次序，保留输入、位置变化和输出的对应证据",
    "reflection": {
        "summary": "栈队列算法实现以状态推演为参照，学生能发现只比较最终输出遗漏的问题。连续操作的中间记录仍需进一步明确。",
        "innovation": "将栈和队列处理同一序列的状态并列展示，再让同伴独立复现，促进学生解释结构规则如何决定输出。",
        "improvement": "下一轮保留一组首次状态偏离的案例，要求学生说明位置更新的原因，并将待验证条件明确移交给下一课。",
    },
}

BOUNDARY_VALIDATION = {
    "task": "验证边界条件与异常处理",
    "focus": "边界条件与异常处理",
    "artifact": "边界测试记录",
    "teaching_content": [
        "以上一课算法实现记录为输入，列出栈队列操作的正常条件和边界条件。区分空结构读取、连续移除和容量限制等情境，先说明预期结果，再安排边界验证，避免把所有失败都视为同一异常。",
        "围绕接口约定执行边界条件与异常处理验证：对正常输入、边界输入和不符合约定的输入分别记录预期结果、实际返回和操作后状态。分析失败是否破坏后续操作，形成能够追查输入与结果的边界测试记录。",
        "根据边界测试记录定位未覆盖条件，比较修订前后的异常处理结果，复核失败之后的数据状态是否仍满足接口约定。汇总已验证范围和待解决问题，完成线性结构成果后再进入下一课的树结构结点模型。",
    ],
    "key_point": {
        "content": ["边界条件与异常处理必须对应明确的输入和预期行为；按接口约定区分正常返回、拒绝操作和异常结果，用边界测试记录保留实际结果及后续状态。"],
        "strategy": ["先写边界输入与预期处理结果，再执行并填写状态变化；对同一种异常比较不同触发条件，核对验证是否覆盖操作约定。"],
    },
    "difficult_point": {
        "content": ["验证边界条件时，既要确认异常处理给出正确结果，也要确认失败没有破坏结构状态；通过连续操作复查修订效果，区分异常现象、原因判断与可复现的验证证据。"],
        "strategy": ["将异常触发步骤与后续正常操作连成测试序列，对照修订前后的边界测试记录，逐项说明结果和状态是否一致。"],
    },
    "goals": {
        "knowledge": ["区分正常条件、边界条件与不符合接口约定的输入。", "说明异常处理结果与失败后结构状态共同构成验证依据。"],
        "ability": ["设计并执行边界条件与异常处理验证，比较预期结果和实际行为。", "依据边界测试记录定位问题，修订后复测并报告覆盖范围。"],
        "quality": ["如实保留异常现象和未覆盖条件，区分观察结果与原因推断。", "在边界验证复核中使用可复现的输入、结果和状态记录支持结论。"],
    },
    "student_analysis": {
        "base": ["已形成栈队列算法实现记录，能够复现正常操作序列。", "已记录实现中尚未覆盖的边界条件，需要转为明确的测试输入。"],
        "problems": ["容易把程序没有中断当作异常处理正确，忽略失败后的结构状态。", "异常记录可能只有结论，没有预期结果和可复现输入。"],
        "strategies": ["将待验证条件转为输入、预期结果和后续操作三项，再实际执行。", "交换边界测试记录独立复测，检查异常处理后是否仍能正常操作。"],
    },
    "stages": [
        ("预读算法实现记录，列出正常条件与待验证的边界条件。", "检查边界条件是否来自接口约定和既有实现问题。", "提交边界条件清单及相应预期结果，保留实现版本。", "把前课成果转化为边界验证的可执行输入。"),
        ("比较空结构读取与正常读取的结果，讨论异常处理约定。", "追问边界条件触发后应返回什么以及应保持什么状态。", "说明边界输入、预期异常结果和后续操作之间的关系。", "建立同时验证结果和状态的检查目标。"),
        ("示范记录边界条件、实际结果与异常处理后的结构状态。", "演示异常处理验证流程，区分观察现象和原因推断。", "完成一条边界测试记录并解释异常结果是否符合接口约定。", "掌握可复现的边界验证记录方法。"),
        ("按条件清单执行正常、边界及不符合约定输入的验证。", "核查边界测试记录中输入、预期结果和实际状态是否对应。", "提交边界测试记录，定位一条异常处理偏差并说明触发输入。", "形成支撑问题定位的完整边界验证证据。"),
        ("在异常处理后继续执行正常操作，检查状态是否被破坏。", "提示学生复查边界条件失败对后续操作的影响。", "补充连续操作的边界验证结果，比较异常前后状态。", "检验异常处理结果与结构状态的一致性。"),
        ("修订存在偏差的异常处理，并复测原边界条件。", "检查边界测试记录是否保留修订前后差异及实现版本。", "提交边界验证复测记录，列出已覆盖和仍未覆盖的条件。", "完成能够复查修订效果的验证交付。"),
        ("交换边界测试记录，复现同伴的异常触发序列。", "要求互评者按边界输入复测，指出缺少预期结果的记录。", "写出边界验证互审结论及证据缺口，反馈覆盖问题。", "独立复核异常处理结论是否有完整依据。"),
        ("归纳边界条件、异常处理结果与后续状态的验证关系。", "说明边界测试记录如何完成线性结构实现的验证闭环。", "报告边界验证范围与待解决问题，明确后续树模型课的入口。", "完成验证成果总结并区分下一课的新教学任务。"),
        ("补齐边界测试记录中的证据缺口，复查异常处理修订。", "反馈边界验证记录是否可独立复现，提示保留未解决条件。", "上传边界测试修订记录及对应实现版本，不删除失败证据。", "巩固按条件、结果和状态复核异常处理的习惯。"),
    ],
    "assessment_signal": "按测试输入复查异常处理结果及后续状态，保留预期结果和实际行为的差异",
    "reflection": {
        "summary": "边界验证促使学生从观察异常结果转向检查失败后的状态。记录可复现输入能够减少仅凭结论判断的问题。",
        "innovation": "把异常触发与后续正常操作组成连续测试，再由同伴复现，使状态破坏和处理约定的差异更容易观察。",
        "improvement": "下一轮增加记录复核环节，要求每个边界验证结论同时提供预期结果、实际状态和对应实现版本。",
    },
}

AUTHORED_PLANS = (STACK_QUEUE, BOUNDARY_VALIDATION)


def apply_authored_fixture_plan(lesson: dict, *, task: str, focus: str, artifact: str) -> None:
    """Apply representative prose only to its matching task/focus/output plan."""
    plan = next((p for p in AUTHORED_PLANS if p['task'] == task), None)
    if plan is None:
        return
    if (focus, artifact) != (plan['focus'], plan['artifact']):
        raise ValueError('authored fixture focus/output conflicts with its task plan')
    for field in ('teaching_content', 'key_point', 'difficult_point', 'goals', 'student_analysis', 'reflection'):
        lesson[field] = copy.deepcopy(plan[field])
    lesson['resources'] = [f"{focus}操作材料", f"{artifact}记录表", '前课接口与实现记录']
    lesson['evaluation']['remarks'] = {
        criterion: f"{text.split('；', 1)[0]}；{plan['assessment_signal']}"
        for criterion, text in lesson['evaluation']['remarks'].items()
    }
    for stage, prose in zip(lesson['implementation'], plan['stages'], strict=True):
        content, teacher, student, objective = prose
        stage.update(content=[content], teacher_actions=[teacher], student_actions=[student], objective=objective)
