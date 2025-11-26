"""Custom Textual widgets for the dashboard."""

import pyperclip
from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from .credentials import ExtractedCredential
from .k8s import PVCStatus, ServiceData
from .models import ServiceConfig


class CopyableCredential(Static):
    """A credential that can be clicked to copy."""

    class Copied(Message):
        """Message sent when credential is copied."""
        def __init__(self, name: str, value: str) -> None:
            self.name = name
            self.value = value
            super().__init__()

    def __init__(
        self,
        name: str,
        credential: ExtractedCredential,
        index: int,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.cred_name = name
        self.credential = credential
        self.index = index

    def render(self) -> RenderableType:
        """Render the credential display."""
        text = Text()
        text.append(f"  [{self.index}] ", style="dim cyan")
        text.append(f"{self.cred_name:<12}", style="cyan")
        text.append(" │ ", style="dim")

        if self.credential.is_valid:
            text.append(self.credential.display_value, style="yellow")
            text.append("  ", style="")
            text.append("[click to copy]", style="dim italic")
        else:
            text.append("<not found>", style="dim red")

        return text

    def on_click(self) -> None:
        """Handle click to copy."""
        if self.credential.is_valid:
            value = self.credential.copyable_value
            try:
                pyperclip.copy(value)
                self.post_message(self.Copied(self.cred_name, value))
            except Exception:
                pass


class ServiceStatusWidget(Static):
    """Widget showing a service's status."""

    def __init__(
        self,
        service_config: ServiceConfig,
        service_data: ServiceData,
        credential: ExtractedCredential | None = None,
        is_last: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.service_config = service_config
        self.service_data = service_data
        self.credential = credential
        self.is_last = is_last

    def render(self) -> RenderableType:
        """Render the service status."""
        text = Text()
        branch = "┗━" if self.is_last else "┣━"

        # Status indicator
        if self.service_data.deployment:
            if self.service_data.deployment.available:
                status = ("✓", "green")
            else:
                status = ("⚠", "yellow")
        else:
            status = ("✗", "red")

        # Service line
        text.append(f"  {branch} ", style="bold")
        text.append(self.service_config.display_name, style="bold")
        text.append(" [", style="")
        text.append(status[0], style=status[1])
        text.append("] ", style="")
        text.append("→ ", style="dim")
        text.append(
            self.service_data.ingress_url or "",
            style="cyan underline"
        )

        # Credential inline
        if self.credential and self.credential.is_valid:
            text.append(" │ ", style="dim")
            display = self.credential.display_value
            if len(display) > 24:
                display = display[:20] + "..."
            text.append(display, style="yellow")

        # Volume mounts
        cont = " " if self.is_last else "┃"
        for pvc in self.service_data.pvcs:
            text.append("\n")
            status_icon = "●" if pvc.phase == "Bound" else "○"
            status_color = "green" if pvc.phase == "Bound" else "yellow"

            text.append(f"  {cont}    ", style="")
            text.append(status_icon, style=status_color)
            text.append(f" {pvc.name}", style="dim")
            text.append(f" ({pvc.capacity})", style="blue")
            text.append(f" [{self._shorten_sc(pvc.storage_class)}]", style="dim")

        return text

    def _shorten_sc(self, sc: str) -> str:
        """Shorten storage class name for display."""
        mapping = {
            "fatboy-nfs-appdata": "nfs:appdata",
            "truenas-nfs": "truenas",
            "synology-nfs": "synology",
            "local-path": "local",
        }
        return mapping.get(sc, sc)


class ServiceGroupWidget(Static):
    """Widget showing a group of services."""

    def __init__(self, name: str, display_name: str, icon: str = "▸", **kwargs):
        super().__init__(**kwargs)
        self.group_name = name
        self.display_name = display_name
        self.icon = icon

    def render(self) -> RenderableType:
        """Render the group header."""
        text = Text()
        text.append(
            f"{self.icon} {self.display_name.upper()}",
            style="magenta bold"
        )
        return text


class StorageSummaryWidget(Static):
    """Widget showing storage summary."""

    def __init__(
        self,
        bound: int,
        pending: int,
        total: int,
        storage_classes: list[str],
        **kwargs
    ):
        super().__init__(**kwargs)
        self.bound = bound
        self.pending = pending
        self.total = total
        self.storage_classes = storage_classes

    def render(self) -> RenderableType:
        """Render the storage summary."""
        text = Text()
        text.append("▸ STORAGE SUMMARY\n", style="magenta bold")
        text.append("  PVCs: ", style="dim")
        text.append(f"{self.bound} Bound", style="green")
        text.append(" ", style="")
        text.append(f"{self.pending} Pending", style="yellow")
        text.append(f" ({self.total} total)\n", style="dim")
        text.append("  Storage Classes: ", style="dim")
        text.append(" ".join(self.storage_classes), style="")
        return text


class ClusterStatusWidget(Static):
    """Widget showing cluster health status."""

    def __init__(self, healthy: bool, **kwargs):
        super().__init__(**kwargs)
        self.healthy = healthy

    def render(self) -> RenderableType:
        """Render the cluster status."""
        text = Text()
        if self.healthy:
            text.append("✓ Cluster is running", style="green bold")
        else:
            text.append("✗ Cluster is not accessible", style="red bold")
        return text


class NotificationWidget(Static):
    """Widget for showing temporary notifications."""

    message = reactive("")

    def render(self) -> RenderableType:
        """Render the notification."""
        if self.message:
            return Text(f"✓ {self.message}", style="green")
        return Text("")

    def show(self, msg: str, duration: float = 2.0) -> None:
        """Show a notification that auto-hides."""
        self.message = msg
        self.set_timer(duration, self._clear)

    def _clear(self) -> None:
        self.message = ""
