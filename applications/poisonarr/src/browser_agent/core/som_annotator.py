"""Set-of-Mark (SoM) Annotator for vision-based browser automation.

SoM annotation overlays numbered markers on interactive elements in screenshots,
allowing vision models to reference specific elements by number rather than
trying to describe element locations.

Reference: "Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V"
https://arxiv.org/abs/2310.11441

STUB: Phase 4 implementation. Core interface defined, full implementation pending.
"""

import base64
import io
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, TYPE_CHECKING

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ElementMark:
    """A marked element on the page."""

    mark_id: int
    """The number shown on the marker."""

    element_type: str
    """Type of element (button, link, input, etc.)."""

    text: str
    """Visible text on the element."""

    bounding_box: Tuple[int, int, int, int]
    """Bounding box (x, y, width, height)."""

    selector: str
    """CSS selector or locator hint."""

    confidence: float = 1.0
    """Detection confidence (for future ML-based detection)."""


@dataclass
class AnnotatedScreenshot:
    """Screenshot with SoM annotations."""

    image_b64: str
    """Base64-encoded annotated PNG image."""

    marks: List[ElementMark]
    """List of marked elements."""

    width: int
    height: int

    def get_mark(self, mark_id: int) -> Optional[ElementMark]:
        """Get element by mark ID."""
        for mark in self.marks:
            if mark.mark_id == mark_id:
                return mark
        return None

    def to_prompt_context(self) -> str:
        """Generate prompt context describing the marks."""
        lines = ["## Interactive Elements (by number)"]
        for mark in self.marks:
            text_preview = mark.text[:30] if mark.text else "(no text)"
            lines.append(f"[{mark.mark_id}] {mark.element_type}: {text_preview}")
        return "\n".join(lines)


class SoMAnnotator:
    """Annotates screenshots with Set-of-Mark numbered markers.

    STUB: Currently uses accessibility tree to identify elements.
    Future: Could use vision models for element detection.
    """

    # Marker styling
    MARKER_SIZE = 24
    MARKER_COLOR = (255, 0, 0)  # Red
    MARKER_TEXT_COLOR = (255, 255, 255)  # White
    MARKER_FONT_SIZE = 14

    # Interactive element roles to mark
    INTERACTIVE_ROLES = [
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "menuitem",
        "tab",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
    ]

    def __init__(self, max_marks: int = 50):
        """Initialize annotator.

        Args:
            max_marks: Maximum number of elements to mark
        """
        self.max_marks = max_marks

        if not HAS_PIL:
            logger.warning("PIL not installed. SoM annotation will be limited.")

    async def annotate(self, page: "Page") -> AnnotatedScreenshot:
        """Annotate a page screenshot with numbered markers.

        Args:
            page: Playwright page to annotate

        Returns:
            AnnotatedScreenshot with marked elements
        """
        # Take screenshot
        screenshot_bytes = await page.screenshot(type="png", full_page=False)

        # Get accessibility tree to find interactive elements
        elements = await self._find_interactive_elements(page)

        # Limit to max marks
        elements = elements[:self.max_marks]

        # Create marks
        marks = [
            ElementMark(
                mark_id=i + 1,
                element_type=elem["role"],
                text=elem.get("name", ""),
                bounding_box=elem.get("bounding_box", (0, 0, 0, 0)),
                selector=elem.get("selector", ""),
            )
            for i, elem in enumerate(elements)
        ]

        # Annotate image if PIL available
        if HAS_PIL and marks:
            annotated_bytes = self._draw_marks(screenshot_bytes, marks)
        else:
            annotated_bytes = screenshot_bytes

        # Get image dimensions
        width, height = 1920, 1080
        if HAS_PIL:
            try:
                img = Image.open(io.BytesIO(screenshot_bytes))
                width, height = img.size
            except Exception:
                pass

        return AnnotatedScreenshot(
            image_b64=base64.b64encode(annotated_bytes).decode(),
            marks=marks,
            width=width,
            height=height,
        )

    async def _find_interactive_elements(self, page: "Page") -> List[dict]:
        """Find interactive elements using accessibility tree.

        Args:
            page: Playwright page

        Returns:
            List of element info dicts
        """
        elements = []

        try:
            # Get accessibility snapshot
            snapshot = await page.accessibility.snapshot()
            if not snapshot:
                return elements

            # Traverse tree and find interactive elements
            self._traverse_a11y_tree(snapshot, elements)

        except Exception as e:
            logger.warning(f"Failed to get accessibility tree: {e}")

        return elements

    def _traverse_a11y_tree(self, node: dict, elements: List[dict], depth: int = 0):
        """Recursively traverse accessibility tree.

        Args:
            node: Current node in tree
            elements: List to append found elements to
            depth: Current depth (for limiting)
        """
        if depth > 10:  # Limit depth
            return

        if len(elements) >= self.max_marks:
            return

        role = node.get("role", "").lower()
        name = node.get("name", "")

        # Check if this is an interactive element
        if role in self.INTERACTIVE_ROLES:
            elements.append({
                "role": role,
                "name": name[:100],
                "bounding_box": (0, 0, 0, 0),  # Would need to get from locator
                "selector": f'[role="{role}"]' + (f':has-text("{name[:30]}")' if name else ""),
            })

        # Traverse children
        for child in node.get("children", []):
            self._traverse_a11y_tree(child, elements, depth + 1)

    def _draw_marks(self, screenshot_bytes: bytes, marks: List[ElementMark]) -> bytes:
        """Draw numbered markers on screenshot.

        STUB: Basic implementation without actual positioning.
        Full implementation would need element bounding boxes.

        Args:
            screenshot_bytes: Original screenshot
            marks: Elements to mark

        Returns:
            Annotated screenshot bytes
        """
        if not HAS_PIL:
            return screenshot_bytes

        try:
            img = Image.open(io.BytesIO(screenshot_bytes))
            draw = ImageDraw.Draw(img)

            # Try to load a font
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", self.MARKER_FONT_SIZE)
            except Exception:
                font = ImageFont.load_default()

            # Draw marks (currently just in corner as placeholder)
            # Real implementation would position at element centers
            for i, mark in enumerate(marks[:10]):  # Only draw first 10 for now
                x = 10
                y = 10 + (i * (self.MARKER_SIZE + 5))

                # Draw circle
                draw.ellipse(
                    [x, y, x + self.MARKER_SIZE, y + self.MARKER_SIZE],
                    fill=self.MARKER_COLOR,
                    outline=(0, 0, 0),
                )

                # Draw number
                text = str(mark.mark_id)
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = x + (self.MARKER_SIZE - text_width) // 2
                text_y = y + (self.MARKER_SIZE - text_height) // 2 - 2
                draw.text((text_x, text_y), text, fill=self.MARKER_TEXT_COLOR, font=font)

            # Save to bytes
            output = io.BytesIO()
            img.save(output, format="PNG")
            return output.getvalue()

        except Exception as e:
            logger.warning(f"Failed to draw marks: {e}")
            return screenshot_bytes


# Convenience function
async def annotate_page(page: "Page", max_marks: int = 50) -> AnnotatedScreenshot:
    """Annotate a page with SoM markers.

    Args:
        page: Playwright page
        max_marks: Maximum markers

    Returns:
        Annotated screenshot
    """
    annotator = SoMAnnotator(max_marks=max_marks)
    return await annotator.annotate(page)


__all__ = ["SoMAnnotator", "ElementMark", "AnnotatedScreenshot", "annotate_page"]
