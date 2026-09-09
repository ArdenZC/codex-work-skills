# G1 Blind Second-pass Instructions

Second-pass Agents are independent and may read only:

- the formal `HTML课件生成器/courseware-html-generator` Skill and its directly referenced contract/Gold-principle files;
- the formal `实践课HTML生成器/practice-class-html-generator` Skill and its directly referenced contract/Gold-principle files;
- the designated frozen raw source pack under `实践课HTML生成器/practice-class-html-generator/holdouts/blind/<course>/`;
- the generic renderer, validator, blueprint and repair scripts.

They must not read `F:\work\blind-generalization-20260907\first-pass`, its `agent-inputs`, any old `holdouts/source-packs` or `holdouts/practice-contracts`, examples, regression cases, other course outputs, or any prior generated contract. They must not edit the repository or overwrite another Agent's directory.

For each course, write only to its assigned `second-agent-inputs/<course>/` directory:

- `courseware-content.json`: Agent-authored Courseware Contract 1.1;
- `practice-content.json`: Agent-authored Practice Contract 1.1;
- `generation-decision.json`: public blueprint and design-decision summary, with no chain-of-thought/private reasoning.

The decision summary must contain valid Courseware and Practice Blueprints. Use the course's own facts to select tasks, starter needs, supports and interactions; do not use fixed task/level/interaction counts. Run the generic runner with `--pass-name second-pass --auto-repair --browser-smoke`; it will preserve Agent inputs, run at most two derived-field repair rounds, revalidate, render and freeze the final package.
