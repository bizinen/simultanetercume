"""
Frame processors for the translation pipeline.
"""

from processors.translator import (
    TranslateToTTSSpeakProcessor,
    InputBufferConfig,
)
from processors.control_processor import ControlProcessor

__all__ = [
    "TranslateToTTSSpeakProcessor",
    "InputBufferConfig",
    "ControlProcessor",
]
