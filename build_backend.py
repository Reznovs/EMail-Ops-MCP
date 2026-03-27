"""Local build backend wrapper to avoid external backend dependency downloads."""

from __future__ import annotations

import setuptools.build_meta as _build_meta


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_editable(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return _build_meta.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    build_hook = getattr(_build_meta, "build_editable", _build_meta.build_wheel)
    return build_hook(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    return _build_meta.build_sdist(sdist_directory, config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _build_meta.prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    prepare_hook = getattr(
        _build_meta,
        "prepare_metadata_for_build_editable",
        _build_meta.prepare_metadata_for_build_wheel,
    )
    return prepare_hook(metadata_directory, config_settings)
