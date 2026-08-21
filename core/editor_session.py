from __future__ import annotations

from dataclasses import dataclass

from .editor_schema import SceneProfile, SkillEditorDocument
from .resource_requirements import requirement_status


@dataclass
class EditorSession:
    document: SkillEditorDocument
    task_media: str | None = None
    media_variant: str | None = None
    dirty: bool = False
    revision: int = 0

    def active_profile(self) -> SceneProfile | None:
        return next(
            (
                profile
                for profile in self.document.scene_profiles
                if profile.scene_profile_id == self.document.active_scene_profile_id
            ),
            None,
        )

    def pending_configuration(self) -> list[dict]:
        profile = self.active_profile()
        if profile is None:
            return [
                {
                    "requirement_id": item.requirement_id,
                    "display_name": item.display_name,
                    "configured": False,
                    "required_before": item.required_before,
                }
                for item in self.document.skill_template.resource_requirements
            ]
        return [
            item
            for item in requirement_status(self.document.skill_template, profile)
            if not item["configured"]
        ]

    def replace_document(self, document: SkillEditorDocument) -> None:
        self.document = document
        self.dirty = True
        self.revision += 1


__all__ = ["EditorSession"]
