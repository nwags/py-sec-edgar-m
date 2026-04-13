from __future__ import annotations

from m_cache_shared.augmentation.models import ApiAugmentationMeta
from m_cache_shared.augmentation.validators import (
    validate_events_view_row,
    validate_run_status_view,
)


def pack_additive_augmentation_meta(
    *,
    augmentation_available: bool,
    augmentation_types_present: list[str],
    last_augmented_at: str | None,
    augmentation_stale: bool | None,
    inspect_path: str | None,
    source_text_version: str | None,
    target_descriptor: dict[str, object] | None,
) -> dict[str, object]:
    return ApiAugmentationMeta(
        augmentation_available=bool(augmentation_available),
        augmentation_types_present=[str(x) for x in augmentation_types_present],
        last_augmented_at=last_augmented_at,
        augmentation_stale=augmentation_stale,
        inspect_path=inspect_path,
        source_text_version=source_text_version,
        target_descriptor=target_descriptor,
    ).model_dump()


def pack_run_status_view(**kwargs: object) -> dict[str, object]:
    return validate_run_status_view(dict(kwargs))


def pack_events_view(**kwargs: object) -> dict[str, object]:
    return validate_events_view_row(dict(kwargs))


# Compatibility aliases retained for the Wave 5.1 normalization cycle.
def build_augmentation_meta_additive(**kwargs: object) -> dict[str, object]:
    return pack_additive_augmentation_meta(**kwargs)


def build_run_status_view(**kwargs: object) -> dict[str, object]:
    return pack_run_status_view(**kwargs)


def build_events_view_row(**kwargs: object) -> dict[str, object]:
    return pack_events_view(**kwargs)


__all__ = [
    "pack_additive_augmentation_meta",
    "pack_run_status_view",
    "pack_events_view",
    "build_augmentation_meta_additive",
    "build_run_status_view",
    "build_events_view_row",
]
