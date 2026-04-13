from __future__ import annotations

def build_augmentation_meta_additive(
    *,
    augmentation_available: bool,
    augmentation_types_present: list[str],
    last_augmented_at: str | None,
    augmentation_stale: bool | None,
    inspect_path: str | None,
    source_text_version: str | None,
    target_descriptor: dict[str, object] | None,
) -> dict[str, object]:
    # Kept local during Wave 6 first external API cycle.
    return {
        "augmentation_available": bool(augmentation_available),
        "augmentation_types_present": [str(x) for x in augmentation_types_present],
        "last_augmented_at": last_augmented_at,
        "augmentation_stale": augmentation_stale,
        "inspect_path": inspect_path,
        "source_text_version": source_text_version,
        "target_descriptor": target_descriptor,
    }

__all__ = ["build_augmentation_meta_additive"]
