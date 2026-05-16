"""Loader for the per-repo `.architecture.yaml` profile."""

from arch_guardian_engine.config.loader import (
    DEFAULT_SCHEMA_PATH,
    ArchitectureProfile,
    ArchitectureSection,
    ConfigError,
    ExceptionRule,
    KnowledgeBase,
    ProjectSection,
    Severity,
    Style,
    UniversalRules,
    load_profile,
    load_profile_from_string,
)

__all__ = [
    "DEFAULT_SCHEMA_PATH",
    "ArchitectureProfile",
    "ArchitectureSection",
    "ConfigError",
    "ExceptionRule",
    "KnowledgeBase",
    "ProjectSection",
    "Severity",
    "Style",
    "UniversalRules",
    "load_profile",
    "load_profile_from_string",
]
