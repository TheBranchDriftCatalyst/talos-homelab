#!/usr/bin/env python3
"""
CLI utilities for corpus-pipelines.

Usage:
    python -m cli env              # Dump env vars as JSON
    python -m cli env --format md  # Dump as markdown
    python -m cli env --format env # Dump as .env.example
    python -m cli validate         # Validate required vars
"""

import argparse
import sys

from corpus_core import dump_env_config, validate_env_config, get_env_registry


def _import_all_assets():
    """Import all asset modules to register their env vars."""
    # Import all domain assets to trigger env var registration
    from domains.congress import assets as congress_assets  # noqa: F401
    from domains.edgar import assets as edgar_assets  # noqa: F401
    from domains.reddit import assets as reddit_assets  # noqa: F401

    # Also import clients which may register vars
    from domains.congress import client as congress_client  # noqa: F401


def cmd_env(args):
    """Dump environment variable configuration."""
    _import_all_assets()

    output = dump_env_config(
        format=args.format,
        include_values=not args.no_values,
    )
    print(output)


def cmd_validate(args):
    """Validate required environment variables."""
    _import_all_assets()

    errors = validate_env_config()
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print("All required environment variables are set.")


def cmd_domains(args):
    """List all registered domains."""
    _import_all_assets()

    registry = get_env_registry()
    domains = registry.domains()

    if not domains:
        print("No domains registered.")
        return

    print("Registered domains:")
    for domain in domains:
        vars_count = len(registry.by_domain(domain))
        print(f"  - {domain}: {vars_count} variable(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Corpus Pipelines CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # env command
    env_parser = subparsers.add_parser("env", help="Dump environment variables")
    env_parser.add_argument(
        "--format", "-f",
        choices=["json", "md", "markdown", "env"],
        default="json",
        help="Output format (default: json)",
    )
    env_parser.add_argument(
        "--no-values",
        action="store_true",
        help="Exclude current values from output",
    )
    env_parser.set_defaults(func=cmd_env)

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate required vars")
    validate_parser.set_defaults(func=cmd_validate)

    # domains command
    domains_parser = subparsers.add_parser("domains", help="List registered domains")
    domains_parser.set_defaults(func=cmd_domains)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
