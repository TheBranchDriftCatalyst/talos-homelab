"""Kubernetes data fetching and caching."""

import base64
import json
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from kubernetes import client, config
from kubernetes.client.rest import ApiException


@dataclass
class PodStatus:
    """Status of a pod."""
    name: str
    phase: str
    ready: bool
    restart_count: int
    created: str


@dataclass
class PVCStatus:
    """Status of a PVC."""
    name: str
    phase: str
    capacity: str
    storage_class: str


@dataclass
class DeploymentStatus:
    """Status of a deployment."""
    name: str
    ready_replicas: int
    replicas: int
    available: bool
    volumes: list[str] = field(default_factory=list)


@dataclass
class ServiceData:
    """Aggregated data for a service."""
    deployment: DeploymentStatus | None
    pods: list[PodStatus]
    pvcs: list[PVCStatus]
    ingress_url: str | None


class K8sClient:
    """Kubernetes client with caching."""

    def __init__(self, namespace: str, domain: str = "talos00"):
        self.namespace = namespace
        self.domain = domain
        self._load_config()

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.custom_api = client.CustomObjectsApi()

        # Cached data
        self._deployments: dict[str, DeploymentStatus] = {}
        self._pods: dict[str, list[PodStatus]] = {}
        self._pvcs: dict[str, PVCStatus] = {}
        self._secrets: dict[str, dict] = {}
        self._ingress_routes: dict[str, str] = {}

    def _load_config(self):
        """Load kubernetes config."""
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()

    def refresh_all(self):
        """Refresh all cached data."""
        self._fetch_deployments()
        self._fetch_pods()
        self._fetch_pvcs()
        self._fetch_secrets()
        self._fetch_ingress_routes()

    def _fetch_deployments(self):
        """Fetch all deployments in namespace."""
        self._deployments = {}
        try:
            deployments = self.apps_v1.list_namespaced_deployment(self.namespace)
            for dep in deployments.items:
                volumes = []
                if dep.spec.template.spec.volumes:
                    for vol in dep.spec.template.spec.volumes:
                        if vol.persistent_volume_claim:
                            volumes.append(vol.persistent_volume_claim.claim_name)

                self._deployments[dep.metadata.name] = DeploymentStatus(
                    name=dep.metadata.name,
                    ready_replicas=dep.status.ready_replicas or 0,
                    replicas=dep.spec.replicas or 0,
                    available=(dep.status.ready_replicas or 0) >= (dep.spec.replicas or 0),
                    volumes=volumes,
                )
        except ApiException as e:
            print(f"Error fetching deployments: {e}")

    def _fetch_pods(self):
        """Fetch all pods in namespace."""
        self._pods = {}
        try:
            pods = self.core_v1.list_namespaced_pod(self.namespace)
            for pod in pods.items:
                app_label = pod.metadata.labels.get("app", "unknown")
                ready = False
                restart_count = 0

                if pod.status.container_statuses:
                    ready = all(cs.ready for cs in pod.status.container_statuses)
                    restart_count = sum(cs.restart_count for cs in pod.status.container_statuses)

                pod_status = PodStatus(
                    name=pod.metadata.name,
                    phase=pod.status.phase,
                    ready=ready,
                    restart_count=restart_count,
                    created=pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else "",
                )

                if app_label not in self._pods:
                    self._pods[app_label] = []
                self._pods[app_label].append(pod_status)
        except ApiException as e:
            print(f"Error fetching pods: {e}")

    def _fetch_pvcs(self):
        """Fetch all PVCs in namespace."""
        self._pvcs = {}
        try:
            pvcs = self.core_v1.list_namespaced_persistent_volume_claim(self.namespace)
            for pvc in pvcs.items:
                capacity = "unknown"
                if pvc.status.capacity:
                    capacity = pvc.status.capacity.get("storage", "unknown")

                self._pvcs[pvc.metadata.name] = PVCStatus(
                    name=pvc.metadata.name,
                    phase=pvc.status.phase,
                    capacity=capacity,
                    storage_class=pvc.spec.storage_class_name or "default",
                )
        except ApiException as e:
            print(f"Error fetching PVCs: {e}")

    def _fetch_secrets(self):
        """Fetch all secrets in namespace."""
        self._secrets = {}
        try:
            secrets = self.core_v1.list_namespaced_secret(self.namespace)
            for secret in secrets.items:
                decoded_data = {}
                if secret.data:
                    for key, value in secret.data.items():
                        try:
                            decoded_data[key] = base64.b64decode(value).decode("utf-8")
                        except Exception:
                            decoded_data[key] = "<binary>"
                self._secrets[secret.metadata.name] = decoded_data
        except ApiException as e:
            print(f"Error fetching secrets: {e}")

    def _fetch_ingress_routes(self):
        """Fetch Traefik IngressRoutes."""
        self._ingress_routes = {}
        try:
            routes = self.custom_api.list_namespaced_custom_object(
                group="traefik.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="ingressroutes",
            )
            for route in routes.get("items", []):
                name = route["metadata"]["name"]
                if "spec" in route and "routes" in route["spec"]:
                    for r in route["spec"]["routes"]:
                        match = r.get("match", "")
                        # Extract host from Host(`hostname`)
                        if "Host(`" in match:
                            host = match.split("Host(`")[1].split("`)")[0]
                            self._ingress_routes[name] = f"http://{host}"
                            break
        except ApiException:
            # IngressRoutes might not exist
            pass

    def get_deployment(self, name: str) -> DeploymentStatus | None:
        """Get deployment status by name."""
        return self._deployments.get(name)

    def get_pods_for_app(self, app_label: str) -> list[PodStatus]:
        """Get pods for an app label."""
        return self._pods.get(app_label, [])

    def get_pvc(self, name: str) -> PVCStatus | None:
        """Get PVC status by name."""
        return self._pvcs.get(name)

    def get_secret_value(self, secret_name: str, key: str) -> str | None:
        """Get a value from a secret."""
        secret = self._secrets.get(secret_name, {})
        return secret.get(key)

    def get_ingress_url(self, service_name: str) -> str | None:
        """Get ingress URL for a service."""
        # Try exact match first
        if service_name in self._ingress_routes:
            return self._ingress_routes[service_name]
        # Try partial match
        for name, url in self._ingress_routes.items():
            if service_name in name:
                return url
        return None

    def get_service_data(self, service_name: str, deployment_name: str | None = None) -> ServiceData:
        """Get aggregated data for a service."""
        dep_name = deployment_name or service_name
        deployment = self.get_deployment(dep_name)
        pods = self.get_pods_for_app(service_name)

        pvcs = []
        if deployment:
            for vol_name in deployment.volumes:
                pvc = self.get_pvc(vol_name)
                if pvc:
                    pvcs.append(pvc)

        ingress_url = self.get_ingress_url(service_name)
        if not ingress_url:
            ingress_url = f"http://{service_name}.{self.domain}"

        return ServiceData(
            deployment=deployment,
            pods=pods,
            pvcs=pvcs,
            ingress_url=ingress_url,
        )

    def exec_in_pod(self, deployment_name: str, command: list[str]) -> str | None:
        """Execute a command in a pod and return stdout."""
        try:
            # Use kubectl exec for simplicity (kubernetes python client exec is complex)
            result = subprocess.run(
                ["kubectl", "exec", "-n", self.namespace, f"deploy/{deployment_name}", "--"] + command,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except Exception:
            return None

    def get_pvc_summary(self) -> dict[str, int]:
        """Get PVC summary counts."""
        bound = sum(1 for pvc in self._pvcs.values() if pvc.phase == "Bound")
        pending = sum(1 for pvc in self._pvcs.values() if pvc.phase == "Pending")
        total = len(self._pvcs)
        return {"bound": bound, "pending": pending, "total": total}

    def get_storage_classes(self) -> list[str]:
        """Get unique storage classes in use."""
        classes = set()
        for pvc in self._pvcs.values():
            classes.add(pvc.storage_class)
        return sorted(classes)

    def namespace_exists(self) -> bool:
        """Check if the namespace exists."""
        try:
            self.core_v1.read_namespace(self.namespace)
            return True
        except ApiException:
            return False

    def cluster_healthy(self) -> bool:
        """Check if the cluster is accessible."""
        try:
            self.core_v1.list_node()
            return True
        except Exception:
            return False
