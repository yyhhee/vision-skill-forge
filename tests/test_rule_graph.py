from __future__ import annotations

import pytest

from core.editor_schema import (
    EventPattern,
    PatternGateway,
    PatternStage,
    ResolvableValue,
    RuleEdge,
    RuleGraph,
    RuleNode,
    TriggerPolicy,
    UserOverride,
)
from core.legacy_importer import import_skill_package
from core.registry import build_default_registry
from core.rule_graph import (
    RuleGraphCompileError,
    RuleGraphCompiler,
    apply_user_overrides,
    validate_rule_graph,
)
from tests.test_editor_document import _package


def _detection_graph():
    return RuleGraph(
        nodes=[
            RuleNode(
                node_id="people",
                kind="target",
                display_name="人员检测",
                operator="rex.ground@1.1",
                params={"targets": [{"label": "人员", "phrases": ["person"]}]},
                output_name="objects",
            )
        ]
    )


def test_rule_graph_compiles_to_existing_executable_package_and_atomic_plan():
    document = import_skill_package(_package())
    document.skill_template.rule_graph = _detection_graph()
    document.skill_template.rule_graphs = {}
    document.skill_template.final_decision = None
    document.skill_template.result_specs = []
    document.skill_template.trigger_policy = TriggerPolicy()

    compiled = RuleGraphCompiler(build_default_registry()).compile_document(
        document, ["image"]
    )

    variant = compiled.effective_skill_package.variants["image"]
    assert [node.id for node in variant.nodes][-1] == "people"
    assert variant.nodes[-1].inputs == {"frames": "$resized"}
    assert variant.outputs == {"objects": "$people"}
    assert compiled.atomic_plan["source"] == "rule_graph"


def test_rule_graph_user_override_changes_only_target_atomic_parameter():
    graph = _detection_graph()
    overrides = [
        UserOverride(
            target_type="atom",
            target_id="people",
            parameter="targets",
            value=[{"label": "车辆", "phrases": ["car"]}],
        )
    ]

    changed = apply_user_overrides(graph, overrides)

    assert graph.nodes[0].params["targets"][0]["label"] == "人员"
    assert changed.nodes[0].params["targets"][0]["label"] == "车辆"


def test_rule_graph_rejects_cycles_and_ambiguous_input_ports():
    graph = RuleGraph(
        nodes=[
            RuleNode(
                node_id="a",
                kind="logic_group",
                display_name="A",
                operator="logic.all@1.0",
            ),
            RuleNode(
                node_id="b",
                kind="logic_group",
                display_name="B",
                operator="logic.any@1.0",
            ),
        ],
        edges=[
            RuleEdge(source="a", target="b", port="invalid"),
            RuleEdge(source="b", target="a"),
        ],
    )

    errors = validate_rule_graph(graph, build_default_registry())
    assert "rule graph contains a cycle" in errors
    assert any("unknown input port invalid" in error for error in errors)

    document = import_skill_package(_package())
    document.skill_template.rule_graph = graph
    document.skill_template.rule_graphs = {}
    with pytest.raises(RuleGraphCompileError):
        RuleGraphCompiler(build_default_registry()).compile_document(document, ["video"])


def test_event_pattern_compiles_independent_branch_durations_and_dynamic_join():
    document = import_skill_package(_package())
    document.skill_template.final_decision = None
    document.skill_template.result_specs = []
    nodes = [
        RuleNode(
            node_id="people",
            kind="target",
            display_name="人员检测",
            operator="rex.ground@1.1",
            params={"targets": [{"label": "人员", "phrases": ["person"]}]},
        ),
        RuleNode(
            node_id="count",
            kind="aggregate",
            display_name="人数",
            operator="reduce.count@1.0",
        ),
    ]
    edges = [RuleEdge(source="people", target="count", port="sets")]
    stage_ids = []
    durations = [0, 10, 0, 3]
    for index, duration in enumerate(durations, start=1):
        node_id = f"branch_{index}"
        stage_ids.append(f"stage_{index}")
        nodes.append(
            RuleNode(
                node_id=node_id,
                kind="condition",
                display_name=f"分支{index}",
                operator="logic.compare@1.0",
                params={"operator": ">=", "value": 1},
            )
        )
        edges.append(RuleEdge(source="count", target=node_id, port="left"))
    document.skill_template.rule_graph = RuleGraph(nodes=nodes, edges=edges)
    document.skill_template.rule_graphs = {}
    document.skill_template.event_patterns = [
        EventPattern(
            pattern_id="multi_area",
            display_name="多区域联合告警",
            stages=[
                PatternStage(
                    stage_id=stage_id,
                    display_name=f"分支{index}",
                    source_rule_id=f"branch_{index}",
                    duration=ResolvableValue(state="explicit", value=durations[index - 1]),
                    persist_mode="continuous" if durations[index - 1] else "immediate",
                )
                for index, stage_id in enumerate(stage_ids, start=1)
            ],
            gateways=[
                PatternGateway(
                    gateway_id="all",
                    mode="all_active",
                    stage_ids=stage_ids,
                )
            ],
            trigger_policy={"cooldown_seconds": 30, "severity": "high"},
        )
    ]

    compiled = RuleGraphCompiler(build_default_registry()).compile_document(
        document, ["video"]
    )
    variant = compiled.effective_skill_package.variants["video"]

    assert sum(node.op == "temporal.qualify@1.0" for node in variant.nodes) == 4
    join = next(node for node in variant.nodes if node.op == "temporal.join@1.0")
    assert join.params["mode"] == "all_active"
    assert len(join.inputs["events"]) == 4
    assert join.params["maximum_matches"] == 1000
    assert variant.outputs["event_multi_area"] == "$pattern_multi_area_trigger_1"
    trigger = next(node for node in variant.nodes if node.op == "event.trigger@2.0")
    assert trigger.params["cooldown_seconds"] == 30


def test_zero_duration_all_active_join_can_compile_for_image():
    document = import_skill_package(_package())
    document.skill_template.final_decision = None
    document.skill_template.result_specs = []
    document.skill_template.rule_graph = RuleGraph(
        nodes=[
            RuleNode(
                node_id="people",
                kind="target",
                display_name="人员检测",
                operator="rex.ground@1.1",
                params={"targets": [{"label": "人员", "phrases": ["person"]}]},
            ),
            RuleNode(
                node_id="count",
                kind="aggregate",
                display_name="人数",
                operator="reduce.count@1.0",
            ),
            RuleNode(
                node_id="branch_a",
                kind="condition",
                display_name="分支A",
                operator="logic.compare@1.0",
                params={"operator": ">=", "value": 1},
            ),
            RuleNode(
                node_id="branch_b",
                kind="condition",
                display_name="分支B",
                operator="logic.compare@1.0",
                params={"operator": ">", "value": 2},
            ),
        ],
        edges=[
            RuleEdge(source="people", target="count", port="sets"),
            RuleEdge(source="count", target="branch_a", port="left"),
            RuleEdge(source="count", target="branch_b", port="left"),
        ],
    )
    document.skill_template.rule_graphs = {}
    document.skill_template.event_patterns = [
        EventPattern(
            pattern_id="all_active",
            display_name="同时满足",
            media_type="image",
            stages=[
                PatternStage(
                    stage_id="stage_a", display_name="分支A", source_rule_id="branch_a"
                ),
                PatternStage(
                    stage_id="stage_b", display_name="分支B", source_rule_id="branch_b"
                ),
            ],
            gateways=[
                PatternGateway(
                    gateway_id="all", mode="all_active", stage_ids=["stage_a", "stage_b"]
                )
            ],
        )
    ]

    compiled = RuleGraphCompiler(build_default_registry()).compile_document(
        document, ["image"]
    )

    assert compiled.effective_skill_package.variants["image"].status == "executable"


def test_region_count_is_frame_local_and_can_compile_for_image():
    document = import_skill_package(_package())
    document.skill_template.final_decision = None
    document.skill_template.result_specs = []
    document.skill_template.event_patterns = []
    document.skill_template.rule_graph = RuleGraph(
        nodes=[
            RuleNode(
                node_id="people",
                kind="target",
                display_name="人员检测",
                operator="rex.ground@1.1",
                params={"targets": [{"label": "人员", "phrases": ["person"]}]},
            ),
            RuleNode(
                node_id="full_frame",
                kind="region",
                display_name="全画面",
                operator="region.full_frame@1.0",
            ),
            RuleNode(
                node_id="region_count",
                kind="aggregate",
                display_name="区域人数",
                operator="measure.region_count@1.0",
            ),
        ],
        edges=[
            RuleEdge(source="people", target="region_count", port="objects"),
            RuleEdge(source="full_frame", target="region_count", port="regions"),
        ],
    )
    document.skill_template.rule_graphs = {}

    compiled = RuleGraphCompiler(build_default_registry()).compile_document(
        document, ["image"]
    )

    variant = compiled.effective_skill_package.variants["image"]
    assert variant.status == "executable"
    assert any(node.op == "measure.region_count@1.0" for node in variant.nodes)
