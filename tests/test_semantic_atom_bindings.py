from __future__ import annotations

from core.registry import build_default_registry
from core.semantic import SemanticNormalizer, WorkflowCompiler
from core.validator import validate_skill_package


def _compiled_package():
    semantic_ir = SemanticNormalizer().normalize_text("检测穿红色上衣、灰色裤子的人。")
    return WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction="检测穿红色上衣、灰色裤子的人。",
        requested_accept=["image", "video"],
        skill_id="red_top_gray_pants_person",
        display_name="红上衣灰裤人员",
    )


def test_every_semantic_atom_is_bound_to_real_nodes_in_each_executable_variant():
    package = _compiled_package()
    atom_ids = {item.atom_id for item in package.semantic_ir.constraints}

    for variant in package.variants.values():
        assert set(variant.atom_bindings) == atom_ids
        node_ids = {node.id for node in variant.nodes}
        assert all(variant.atom_bindings[atom_id] for atom_id in atom_ids)
        assert all(
            node_id in node_ids
            for bound in variant.atom_bindings.values()
            for node_id in bound
        )


def test_package_validator_rejects_an_unbound_semantic_atom():
    package = _compiled_package()
    del package.variants["image"].atom_bindings["atom_2"]

    errors = validate_skill_package(package, build_default_registry())

    assert "image: semantic atom atom_2 is not bound to workflow nodes" in errors


def test_package_validator_rejects_binding_to_unknown_node():
    package = _compiled_package()
    package.variants["video"].atom_bindings["atom_1"] = ["missing_node"]

    errors = validate_skill_package(package, build_default_registry())

    assert "video: semantic atom atom_1 binds unknown node missing_node" in errors
