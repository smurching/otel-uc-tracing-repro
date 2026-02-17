#!/usr/bin/env python3
"""
Minimal repro: OTel traces don't appear in Unity Catalog tables created by MLflow API.

Prerequisites:
    pip install 'mlflow[databricks]>=3.9.0' opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http databricks-sdk
    databricks auth login --profile dogfood
"""
import os
import json
import time
import subprocess
import mlflow
from mlflow.entities import UCSchemaLocation
from mlflow.tracing.enablement import set_experiment_trace_location
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from databricks.sdk import WorkspaceClient

# Config
WORKSPACE = "https://e2-dogfood.staging.cloud.databricks.com"
PROFILE = "dogfood"
EXPERIMENT = "/Users/sid.murching@databricks.com/otel-repro-minimal"
CATALOG = "main"
SCHEMA = "agent_traces"

print("Setting up MLflow experiment and UC tables...")

# Get auth
result = subprocess.run(["databricks", "auth", "token", "--profile", PROFILE],
                       capture_output=True, text=True, check=True)
token = json.loads(result.stdout)["access_token"]

# Get warehouse
w = WorkspaceClient(profile=PROFILE)
warehouse_id = next(wh.id for wh in w.warehouses.list()
                    if wh.state and wh.state.value == "RUNNING")
os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = warehouse_id

# Create experiment and link to UC
mlflow.set_tracking_uri("databricks")
os.environ["DATABRICKS_HOST"] = WORKSPACE
os.environ["DATABRICKS_CONFIG_PROFILE"] = PROFILE

if experiment := mlflow.get_experiment_by_name(EXPERIMENT):
    experiment_id = experiment.experiment_id
else:
    experiment_id = mlflow.create_experiment(name=EXPERIMENT)

print(f"Linking experiment {experiment_id} to {CATALOG}.{SCHEMA}...")
try:
    result = set_experiment_trace_location(
        location=UCSchemaLocation(catalog_name=CATALOG, schema_name=SCHEMA),
        experiment_id=experiment_id,
    )
    table_name = result.full_otel_spans_table_name
    print(f"✓ Tables created: {table_name}")
except Exception as e:
    # API often times out but tables still get created
    table_name = f"{CATALOG}.{SCHEMA}.mlflow_experiment_trace_otel_spans"
    print(f"API error (may be expected): {e}")
    print(f"Checking if table exists anyway...")
    w.tables.get(full_name=table_name)  # Will raise if doesn't exist
    print(f"✓ Table exists: {table_name}")

# Send test trace
print("\nSending test trace via OTel...")
resource = Resource.create({"service.name": "test", "mlflow.experimentId": str(experiment_id)})
exporter = OTLPSpanExporter(
    endpoint=f"{WORKSPACE}/api/2.0/otel/v1/traces",
    headers={
        "content-type": "application/x-protobuf",
        "X-Databricks-UC-Table-Name": table_name,
        "Authorization": f"Bearer {token}"
    },
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

with provider.get_tracer(__name__).start_as_current_span("test-span") as span:
    span.set_attribute("test", "value")

provider.force_flush()
print("✓ Trace sent")

# Wait and verify
print("\nWaiting 20s for trace to appear in UC...")
time.sleep(20)

# Query UC table
sql = f"SELECT * FROM {table_name} WHERE name = 'test-span' LIMIT 1"
result = w.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement=sql,
    wait_timeout="60s"
)

# Assert traces appear
status = result.status.state.value if result.status and result.status.state else "UNKNOWN"
has_data = (status == "SUCCEEDED" and
            result.result and result.result.data_array and
            len(result.result.data_array) > 0)

if not has_data:
    error_msg = result.status.error.message if result.status and result.status.error else "No data"
    print(f"\n❌ FAILED: Traces not found in UC table")
    print(f"   Query status: {status}")
    print(f"   Error: {error_msg[:200] if error_msg else 'Table empty'}")
    print(f"\n🐛 Issues found:")
    print(f"   1. MLflow API creates tables with 'Incomplete complex type' errors")
    print(f"   2. Tables are not queryable")
    print(f"   3. Even if queryable, traces don't appear (backend issue)")
    raise AssertionError("Traces not found in Unity Catalog table")

print(f"✓ SUCCESS: Trace found in UC table!")
