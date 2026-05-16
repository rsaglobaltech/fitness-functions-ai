"""Gold dataset loader (F0.5).

Reads YAML cases from `packages/catalog/datasets/gold-v*/cases/**/*.yaml`,
validates against the JSON Schema bundled with the dataset, and returns
typed `GoldCase` instances suitable for evaluation pipelines.
"""

from arch_guardian_engine.gold_dataset.loader import (
    GoldCase,
    GoldCodeFile,
    GoldDataset,
    GoldSource,
    InvalidGoldCaseError,
    Label,
    Severity,
    load_dataset,
)

__all__ = [
    "GoldCase",
    "GoldCodeFile",
    "GoldDataset",
    "GoldSource",
    "InvalidGoldCaseError",
    "Label",
    "Severity",
    "load_dataset",
]
