"""Core browser automation components."""

from .navigator import Navigator
from .code_navigator import CodeNavigator
from .browser import BrowserController, BrowserTools
from .vision import VisionAnalyzer, is_vision_available
from .error_tracker import PlaywrightErrorTracker
from .som_annotator import SoMAnnotator, ElementMark, AnnotatedScreenshot, annotate_page

__all__ = [
    "Navigator",
    "CodeNavigator",
    "BrowserController",
    "BrowserTools",
    "VisionAnalyzer",
    "is_vision_available",
    "PlaywrightErrorTracker",
    "SoMAnnotator",
    "ElementMark",
    "AnnotatedScreenshot",
    "annotate_page",
]
