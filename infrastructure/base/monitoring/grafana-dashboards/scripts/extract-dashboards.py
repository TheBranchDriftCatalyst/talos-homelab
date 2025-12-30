#!/usr/bin/env python3
"""
Extract JSON dashboards from existing GrafanaDashboard CRs.
Creates standalone JSON files and new CR templates with configMapRef.
"""

import yaml
import json
import os
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent.parent
JSON_DIR = DASHBOARD_DIR / "json"
RESOURCES_DIR = DASHBOARD_DIR / "resources"

def extract_dashboards():
    """Extract JSON from all GrafanaDashboard YAMLs."""

    JSON_DIR.mkdir(exist_ok=True)
    RESOURCES_DIR.mkdir(exist_ok=True)

    dashboard_files = list(DASHBOARD_DIR.glob("*.yaml"))
    dashboard_files = [f for f in dashboard_files if f.name != "kustomization.yaml"]

    extracted = []

    for yaml_file in sorted(dashboard_files):
        print(f"Processing: {yaml_file.name}")

        with open(yaml_file, 'r') as f:
            content = f.read()

        # Handle multi-document YAML
        docs = list(yaml.safe_load_all(content))

        for doc in docs:
            if not doc:
                continue

            # Check if it's a GrafanaDashboard
            if doc.get('kind') != 'GrafanaDashboard':
                print(f"  Skipping non-GrafanaDashboard: {doc.get('kind', 'unknown')}")
                continue

            metadata = doc.get('metadata', {})
            spec = doc.get('spec', {})
            name = metadata.get('name', 'unknown')

            # Get the JSON content
            json_str = spec.get('json')
            if not json_str:
                # Check for url or configMapRef (already using external source)
                if spec.get('url') or spec.get('configMapRef'):
                    print(f"  {name}: Already using external source, skipping")
                    continue
                print(f"  {name}: No inline JSON found, skipping")
                continue

            # Parse and pretty-print the JSON
            try:
                dashboard_json = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"  {name}: Invalid JSON - {e}")
                continue

            # Get dashboard UID and title for filename
            uid = dashboard_json.get('uid', name)
            title = dashboard_json.get('title', name)

            # Create clean filename from name
            json_filename = f"{name}.json"
            json_path = JSON_DIR / json_filename

            # Write pretty-printed JSON
            with open(json_path, 'w') as f:
                json.dump(dashboard_json, f, indent=2)

            print(f"  Extracted: {json_filename} ({title})")

            # Create new GrafanaDashboard CR with configMapRef
            new_cr = {
                'apiVersion': 'grafana.integreatly.org/v1beta1',
                'kind': 'GrafanaDashboard',
                'metadata': {
                    'name': name,
                    'namespace': metadata.get('namespace', 'monitoring'),
                    'labels': metadata.get('labels', {})
                },
                'spec': {
                    'instanceSelector': spec.get('instanceSelector', {
                        'matchLabels': {'dashboards': 'grafana'}
                    }),
                    'configMapRef': {
                        'name': f"dashboard-{name}",
                        'key': json_filename
                    }
                }
            }

            # Preserve folder if set
            if spec.get('folder'):
                new_cr['spec']['folder'] = spec['folder']

            # Preserve datasources mapping if set
            if spec.get('datasources'):
                new_cr['spec']['datasources'] = spec['datasources']

            # Write new CR
            cr_path = RESOURCES_DIR / f"{name}.yaml"
            with open(cr_path, 'w') as f:
                f.write("---\n")
                yaml.dump(new_cr, f, default_flow_style=False, sort_keys=False)

            extracted.append({
                'name': name,
                'json_file': json_filename,
                'configmap_name': f"dashboard-{name}",
                'folder': spec.get('folder', 'General')
            })

    return extracted


def generate_kustomization(extracted):
    """Generate new kustomization.yaml with configMapGenerator."""

    # ConfigMap generator entries
    configmaps = []
    for dash in extracted:
        configmaps.append({
            'name': dash['configmap_name'],
            'files': [f"json/{dash['json_file']}"]
        })

    # Resource entries (the new CRs)
    resources = [f"resources/{dash['name']}.yaml" for dash in extracted]

    kustomization = {
        'apiVersion': 'kustomize.config.k8s.io/v1beta1',
        'kind': 'Kustomization',
        'namespace': 'monitoring',
        'configMapGenerator': configmaps,
        'generatorOptions': {
            'disableNameSuffixHash': True  # Keep predictable names
        },
        'resources': resources
    }

    kust_path = DASHBOARD_DIR / "kustomization.new.yaml"
    with open(kust_path, 'w') as f:
        f.write("---\n")
        yaml.dump(kustomization, f, default_flow_style=False, sort_keys=False)

    print(f"\nGenerated: kustomization.new.yaml")
    print(f"  - {len(configmaps)} ConfigMaps")
    print(f"  - {len(resources)} GrafanaDashboard resources")


def main():
    print("=" * 60)
    print("Extracting Grafana Dashboards")
    print("=" * 60)

    extracted = extract_dashboards()

    if not extracted:
        print("\nNo dashboards extracted!")
        return 1

    print(f"\n{'=' * 60}")
    print(f"Extracted {len(extracted)} dashboards")
    print("=" * 60)

    generate_kustomization(extracted)

    print("\nNext steps:")
    print("  1. Review json/ directory for extracted dashboards")
    print("  2. Review resources/ directory for new CRs")
    print("  3. Replace kustomization.yaml with kustomization.new.yaml")
    print("  4. Delete old embedded YAML files")
    print("  5. Run: kubectl apply -k .")

    return 0


if __name__ == '__main__':
    sys.exit(main())
