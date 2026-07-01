from dataclasses import dataclass


@dataclass(frozen=True)
class LiteratureEntitySchema:
    name: str
    name_zh: str
    properties: tuple[tuple[str, str, str], ...]
    relations: tuple[tuple[str, str, str], ...] = ()


LITERATURE_ENTITIES: tuple[LiteratureEntitySchema, ...] = (
    LiteratureEntitySchema(
        name="Paper",
        name_zh="论文",
        properties=(
            ("paperId", "论文ID", "Text"),
            ("title", "标题", "Text"),
            ("authors", "作者", "Text"),
            ("year", "年份", "Text"),
            ("journal", "期刊", "Text"),
            ("doi", "DOI", "Text"),
            ("abstract", "摘要", "Text"),
            ("keywords", "关键词", "Text"),
            ("documentId", "文档ID", "Text"),
        ),
        relations=(
            ("proposes", "提出方法", "Method"),
            ("uses", "使用材料", "Material"),
            ("hasCondition", "实验条件", "Condition"),
            ("measures", "评价指标", "Metric"),
            ("reports", "报告结果", "Result"),
            ("drawsConclusion", "得出结论", "Conclusion"),
            ("hasEvidence", "原文证据", "Evidence"),
        ),
    ),
    LiteratureEntitySchema(
        name="Method",
        name_zh="方法",
        properties=(
            ("methodId", "方法ID", "Text"),
            ("name", "名称", "Text"),
            ("description", "描述", "Text"),
            ("methodType", "方法类型", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Material",
        name_zh="材料",
        properties=(
            ("materialId", "材料ID", "Text"),
            ("name", "名称", "Text"),
            ("type", "类型", "Text"),
            ("description", "描述", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Condition",
        name_zh="条件",
        properties=(
            ("conditionId", "条件ID", "Text"),
            ("name", "名称", "Text"),
            ("value", "数值", "Text"),
            ("unit", "单位", "Text"),
            ("normalizedValue", "归一化数值", "Text"),
            ("normalizedUnit", "归一化单位", "Text"),
            ("description", "描述", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Metric",
        name_zh="指标",
        properties=(
            ("metricId", "指标ID", "Text"),
            ("name", "名称", "Text"),
            ("value", "数值", "Text"),
            ("unit", "单位", "Text"),
            ("description", "描述", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Result",
        name_zh="结果",
        properties=(
            ("resultId", "结果ID", "Text"),
            ("description", "描述", "Text"),
            ("value", "数值", "Text"),
            ("unit", "单位", "Text"),
            ("resultType", "结果类型", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Conclusion",
        name_zh="结论",
        properties=(
            ("conclusionId", "结论ID", "Text"),
            ("description", "描述", "Text"),
            ("scope", "适用范围", "Text"),
        ),
        relations=(("supportedBy", "证据支持", "Evidence"),),
    ),
    LiteratureEntitySchema(
        name="Evidence",
        name_zh="证据",
        properties=(
            ("evidenceId", "证据ID", "Text"),
            ("documentId", "文档ID", "Text"),
            ("chunkId", "文本块ID", "Text"),
            ("page", "页码", "Text"),
            ("sectionTitle", "章节标题", "Text"),
            ("sourceText", "原文", "Text"),
            ("offsetStart", "起始偏移", "Text"),
            ("offsetEnd", "结束偏移", "Text"),
            ("paperId", "论文ID", "Text"),
        ),
    ),
)


def literature_entity_names() -> list[str]:
    return [entity.name for entity in LITERATURE_ENTITIES]


def build_literature_schema_script(existing_script: str = "", namespace: str = "LabKAG") -> str:
    base_script = _remove_literature_entity_blocks(existing_script.strip())
    blocks = [base_script or f"namespace {namespace}"]
    for entity in LITERATURE_ENTITIES:
        blocks.append(_entity_to_kgdsl(entity))
    return "\n\n".join(block for block in blocks if block).strip() + "\n"


def _remove_literature_entity_blocks(script: str) -> str:
    entity_prefixes = tuple(f"{name}(" for name in literature_entity_names())
    kept: list[str] = []
    skipping = False
    for line in script.splitlines():
        is_top_level = line and not line.startswith((" ", "\t"))
        if is_top_level:
            skipping = line.startswith(entity_prefixes)
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip()


def _entity_to_kgdsl(entity: LiteratureEntitySchema) -> str:
    lines = [f"{entity.name}({entity.name_zh}): EntityType", "\tproperties:"]
    for name, name_zh, value_type in entity.properties:
        lines.append(f"\t\t{name}({name_zh}): {value_type}")
    if entity.relations:
        lines.append("\trelations:")
        for name, name_zh, target in entity.relations:
            lines.append(f"\t\t{name}({name_zh}): {target}")
    return "\n".join(lines)
