"""Style-specific, deterministic rules driven by `.architecture.yaml` `layout`."""

from arch_guardian_engine.rules.layers import (
    LayerSpec,
    detect_layer_violations,
    parse_layers,
)

__all__ = ["LayerSpec", "detect_layer_violations", "parse_layers"]
