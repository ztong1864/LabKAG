from app.adapters.labkag_schema import build_literature_schema_script, literature_entity_names


def test_literature_entity_names_are_scoped_to_v0_1_literature_schema():
    assert literature_entity_names() == [
        "Paper",
        "Method",
        "Material",
        "Condition",
        "Metric",
        "Result",
        "Conclusion",
        "Evidence",
    ]


def test_build_literature_schema_script_appends_missing_entities():
    script = build_literature_schema_script("namespace LabKAG\n\nChunk(文本块): EntityType")

    assert "namespace LabKAG" in script
    assert "Chunk(文本块): EntityType" in script
    assert "Paper(论文): EntityType" in script
    assert "\t\tpaperId(论文ID): Text" in script
    assert "\t\thasCondition(实验条件): Condition" in script
    assert "\t\tsupportedBy(证据支持): Evidence" in script
    assert "Condition(条件): EntityType" in script
    assert "Evidence(证据): EntityType" in script
    assert "Author(" not in script
    assert "ResearchProblem(" not in script


def test_build_literature_schema_script_replaces_existing_literature_entities():
    script = build_literature_schema_script(
        "namespace LabKAG\n\nPaper(论文): EntityType\n\tproperties:\n\t\ttitle(标题): Text"
    )

    assert script.count("Paper(论文): EntityType") == 1
    assert "\t\tpaperId(论文ID): Text" in script
