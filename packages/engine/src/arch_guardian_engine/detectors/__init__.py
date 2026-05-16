"""Universal detectors run on every repository regardless of style."""

from arch_guardian_engine.detectors.circular_dependencies import (
    detect_circular_dependencies,
)
from arch_guardian_engine.detectors.complexity import (
    detect_cyclomatic_complexity,
)
from arch_guardian_engine.detectors.god_object import detect_god_objects

__all__ = [
    "detect_circular_dependencies",
    "detect_cyclomatic_complexity",
    "detect_god_objects",
]
