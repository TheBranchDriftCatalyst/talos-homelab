"""
Dagster Definitions - Congress ETL Pipeline

Main entry point for Dagster code server.
Defines assets, jobs, schedules, and resources.
"""

import os

from dagster import (
    Definitions,
    ScheduleDefinition,
    define_asset_job,
    load_assets_from_modules,
    EnvVar,
)
from dagster_k8s import k8s_job_executor

from domains import congressional


# ============================================================================
# Load Assets
# ============================================================================

# Load all assets from congressional domain
congressional_assets = load_assets_from_modules([congressional])


# ============================================================================
# Jobs
# ============================================================================

# Full ETL job - runs all congressional assets
congress_etl_job = define_asset_job(
    name="congress_etl_job",
    selection="*",  # All assets
    description="Full Congress.gov ETL pipeline: extract -> transform -> entities -> graph",
    tags={
        "domain": "congressional",
    },
    # k8s_job_executor - each asset step runs as a separate K8s Job
    executor_def=k8s_job_executor.configured({
        "job_namespace": os.environ.get("DAGSTER_NAMESPACE", "scratch"),
        "step_k8s_config": {
            "container_config": {
                "resources": {
                    "requests": {"cpu": "200m", "memory": "512Mi"},
                    "limits": {"cpu": "1000m", "memory": "2Gi"},
                },
                "env": [
                    {"name": "CONGRESS_API_KEY", "valueFrom": {"secretKeyRef": {"name": "congress-api-credentials", "key": "API_KEY"}}},
                    {"name": "NEO4J_URI", "valueFrom": {"secretKeyRef": {"name": "neo4j-credentials", "key": "NEO4J_URI"}}},
                    {"name": "NEO4J_USER", "valueFrom": {"secretKeyRef": {"name": "neo4j-credentials", "key": "NEO4J_USER"}}},
                    {"name": "NEO4J_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "neo4j-credentials", "key": "NEO4J_PASSWORD"}}},
                    {"name": "OLLAMA_URL", "value": os.environ.get("OLLAMA_URL", "http://ollama-local.catalyst-llm.svc.cluster.local:11434")},
                    {"name": "S3_ENDPOINT_URL", "value": os.environ.get("S3_ENDPOINT_URL", "http://minio.minio.svc.cluster.local")},
                ],
            },
            "pod_spec_config": {
                "service_account_name": "dagster-run",
            },
        },
    }),
)

# Extraction only job - just raw data
congress_extract_job = define_asset_job(
    name="congress_extract_job",
    selection=["congress_bills", "congress_members", "congress_committees"],
    description="Extract raw data from Congress.gov API",
    tags={"domain": "congressional", "stage": "extract"},
)


# ============================================================================
# Schedules
# ============================================================================

# Daily full ETL at 2 AM UTC
daily_etl_schedule = ScheduleDefinition(
    job=congress_etl_job,
    # TODO: change this to be every hour
    cron_schedule="0 2 * * *",  # 2 AM UTC daily
    execution_timezone="UTC",
)

# Weekly extraction on Sundays at midnight
weekly_extract_schedule = ScheduleDefinition(
    job=congress_extract_job,
    cron_schedule="0 0 * * 0",  # Midnight UTC on Sundays
    execution_timezone="UTC",
)


# ============================================================================
# Resources (Dagster Resources for dependency injection)
# ============================================================================

# Resources are configured via environment variables in the job executor
# This keeps the code simple and configuration in K8s secrets


# ============================================================================
# Definitions
# ============================================================================

defs = Definitions(
    assets=congressional_assets,
    jobs=[congress_etl_job, congress_extract_job],
    schedules=[daily_etl_schedule, weekly_extract_schedule],
)
