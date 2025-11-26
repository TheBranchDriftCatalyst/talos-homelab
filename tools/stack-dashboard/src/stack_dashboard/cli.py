"""CLI entry point for stack dashboard."""

import argparse
import sys
from pathlib import Path

import yaml

from .app import StackDashboardApp
from .models import (
    CredentialConfig,
    CredentialSource,
    CredentialType,
    ServiceConfig,
    ServiceGroup,
    StackConfig,
)


def load_config_from_yaml(path: Path) -> StackConfig:
    """Load stack configuration from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    groups = []
    for group_data in data.get("groups", []):
        services = []
        for svc_data in group_data.get("services", []):
            cred_data = svc_data.get("credential")
            credential = None
            if cred_data:
                credential = CredentialConfig(
                    name=cred_data.get("name", svc_data["name"]),
                    display_name=cred_data.get("display_name", svc_data.get("display_name", svc_data["name"])),
                    type=CredentialType(cred_data.get("type", "api_key")),
                    source=CredentialSource(cred_data.get("source", "secret")),
                    secret_name=cred_data.get("secret_name"),
                    secret_key=cred_data.get("secret_key"),
                    config_path=cred_data.get("config_path"),
                    json_path=cred_data.get("json_path"),
                    xml_tag=cred_data.get("xml_tag"),
                    xml_attribute=cred_data.get("xml_attribute"),
                    username_key=cred_data.get("username_key"),
                    password_key=cred_data.get("password_key"),
                    static_username=cred_data.get("static_username"),
                )

            services.append(ServiceConfig(
                name=svc_data["name"],
                display_name=svc_data.get("display_name", svc_data["name"]),
                description=svc_data.get("description", ""),
                deployment_name=svc_data.get("deployment_name"),
                namespace=svc_data.get("namespace"),
                url_template=svc_data.get("url_template", "http://{name}.{domain}"),
                port=svc_data.get("port"),
                credential=credential,
                show_volumes=svc_data.get("show_volumes", True),
                optional=svc_data.get("optional", False),
                icon=svc_data.get("icon", "●"),
            ))

        groups.append(ServiceGroup(
            name=group_data["name"],
            display_name=group_data.get("display_name", group_data["name"]),
            services=services,
            icon=group_data.get("icon", "▸"),
        ))

    # Global credentials
    global_credentials = []
    for cred_data in data.get("global_credentials", []):
        global_credentials.append(CredentialConfig(
            name=cred_data["name"],
            display_name=cred_data.get("display_name", cred_data["name"]),
            type=CredentialType(cred_data.get("type", "api_key")),
            source=CredentialSource(cred_data.get("source", "secret")),
            secret_name=cred_data.get("secret_name"),
            secret_key=cred_data.get("secret_key"),
            config_path=cred_data.get("config_path"),
            json_path=cred_data.get("json_path"),
            xml_tag=cred_data.get("xml_tag"),
            xml_attribute=cred_data.get("xml_attribute"),
            username_key=cred_data.get("username_key"),
            password_key=cred_data.get("password_key"),
            static_username=cred_data.get("static_username"),
        ))

    return StackConfig(
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        namespace=data["namespace"],
        domain=data.get("domain", "talos00"),
        groups=groups,
        global_credentials=global_credentials,
        banner=data.get("banner"),
        refresh_interval=data.get("refresh_interval", 5.0),
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Stack Dashboard - Kubernetes stack monitoring TUI")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        help="Path to stack configuration YAML file",
    )
    parser.add_argument(
        "--namespace", "-n",
        type=str,
        default="media-prod",
        help="Kubernetes namespace (default: media-prod)",
    )
    parser.add_argument(
        "--domain", "-d",
        type=str,
        default="talos00",
        help="Domain for service URLs (default: talos00)",
    )

    args = parser.parse_args()

    if args.config:
        config = load_config_from_yaml(args.config)
    else:
        # Default minimal config
        config = StackConfig(
            name="default",
            display_name="Kubernetes Stack",
            namespace=args.namespace,
            domain=args.domain,
        )

    app = StackDashboardApp(config)
    app.run()


if __name__ == "__main__":
    main()
