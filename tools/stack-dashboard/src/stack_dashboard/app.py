"""Main Textual application for stack dashboard."""

import pyperclip
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Static

from .credentials import CredentialExtractor, ExtractedCredential
from .k8s import K8sClient
from .models import StackConfig
from .widgets import (
    ClusterStatusWidget,
    CopyableCredential,
    NotificationWidget,
    ServiceGroupWidget,
    ServiceStatusWidget,
    StorageSummaryWidget,
)


class StackDashboardApp(App):
    """Main dashboard application."""

    CSS = """
    Screen {
        background: $surface;
    }

    #banner {
        text-align: center;
        padding: 1;
        color: $accent;
    }

    #main-content {
        padding: 1 2;
    }

    #credentials-section {
        margin-top: 1;
        padding: 1;
        border: solid $primary;
    }

    #credentials-title {
        text-style: bold;
        color: $accent;
    }

    #notification {
        dock: bottom;
        height: 1;
        padding: 0 1;
    }

    .service-group {
        margin-bottom: 1;
    }

    CopyableCredential {
        height: 1;
    }

    CopyableCredential:hover {
        background: $primary 20%;
    }

    Footer {
        background: $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "copy_credential(1)", "Copy 1", show=False),
        Binding("2", "copy_credential(2)", "Copy 2", show=False),
        Binding("3", "copy_credential(3)", "Copy 3", show=False),
        Binding("4", "copy_credential(4)", "Copy 4", show=False),
        Binding("5", "copy_credential(5)", "Copy 5", show=False),
        Binding("6", "copy_credential(6)", "Copy 6", show=False),
        Binding("7", "copy_credential(7)", "Copy 7", show=False),
        Binding("8", "copy_credential(8)", "Copy 8", show=False),
        Binding("9", "copy_credential(9)", "Copy 9", show=False),
        Binding("0", "copy_credential(10)", "Copy 10", show=False),
    ]

    def __init__(self, config: StackConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.k8s = K8sClient(config.namespace, config.domain)
        self.cred_extractor = CredentialExtractor(self.k8s)
        self.credentials: list[tuple[str, ExtractedCredential]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Static(id="banner"),
            Container(id="main-content"),
            id="scroll-container",
        )
        yield NotificationWidget(id="notification")
        yield Footer()

    def on_mount(self) -> None:
        """Initial data load."""
        self.title = self.config.display_name
        self.sub_title = f"Namespace: {self.config.namespace}"
        self._render_banner()
        self.action_refresh()

        # Set up auto-refresh
        if self.config.refresh_interval > 0:
            self.set_interval(self.config.refresh_interval, self.action_refresh)

    def _render_banner(self) -> None:
        """Render the ASCII banner."""
        banner = self.query_one("#banner", Static)
        if self.config.banner:
            banner.update(Text(self.config.banner, style="cyan bold"))
        else:
            banner.update(Text(f"⚡ {self.config.display_name} ⚡", style="cyan bold"))

    def action_refresh(self) -> None:
        """Refresh all data."""
        self.k8s.refresh_all()
        self._render_content()

    def _render_content(self) -> None:
        """Render the main content."""
        container = self.query_one("#main-content", Container)
        container.remove_children()

        self.credentials = []

        # Cluster status
        container.mount(ClusterStatusWidget(self.k8s.cluster_healthy()))
        container.mount(Static(""))

        # Service groups
        for group in self.config.groups:
            container.mount(ServiceGroupWidget(group.name, group.display_name, group.icon))

            for i, service in enumerate(group.services):
                is_last = i == len(group.services) - 1
                service_data = self.k8s.get_service_data(service.name, service.deployment_name)

                # Extract credential if configured
                credential = None
                if service.credential:
                    credential = self.cred_extractor.extract(
                        service.credential,
                        service.deployment_name or service.name,
                    )
                    if credential.is_valid or not service.optional:
                        self.credentials.append((service.display_name, credential))

                # Check if optional service exists
                if service.optional and not service_data.deployment:
                    text = Text()
                    branch = "┗━" if is_last else "┣━"
                    text.append(f"  {branch} ", style="dim")
                    text.append(f"{service.display_name} (not deployed)", style="dim")
                    container.mount(Static(text))
                else:
                    container.mount(ServiceStatusWidget(
                        service,
                        service_data,
                        credential,
                        is_last,
                    ))

            container.mount(Static(""))

        # Storage summary
        pvc_summary = self.k8s.get_pvc_summary()
        storage_classes = self.k8s.get_storage_classes()
        container.mount(StorageSummaryWidget(
            pvc_summary["bound"],
            pvc_summary["pending"],
            pvc_summary["total"],
            storage_classes,
        ))

        # Credentials section
        container.mount(Static(""))
        container.mount(Static(Text("▸ CREDENTIALS (click or press number to copy)", style="magenta bold")))

        for i, (name, cred) in enumerate(self.credentials, 1):
            container.mount(CopyableCredential(name, cred, i))

        # Global credentials
        for cred_config in self.config.global_credentials:
            cred = self.cred_extractor.extract(cred_config)
            self.credentials.append((cred_config.display_name, cred))
            container.mount(CopyableCredential(cred_config.display_name, cred, len(self.credentials)))

    def on_copyable_credential_copied(self, event: CopyableCredential.Copied) -> None:
        """Handle credential copy event."""
        notification = self.query_one("#notification", NotificationWidget)
        notification.show(f"Copied {event.name} to clipboard")

    def action_copy_credential(self, index: int) -> None:
        """Copy credential by index (1-based)."""
        if 1 <= index <= len(self.credentials):
            name, cred = self.credentials[index - 1]
            if cred.is_valid:
                try:
                    pyperclip.copy(cred.copyable_value)
                    notification = self.query_one("#notification", NotificationWidget)
                    notification.show(f"Copied {name} to clipboard")
                except Exception:
                    pass

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
