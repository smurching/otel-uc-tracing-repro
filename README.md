# OTel Tracing to Unity Catalog - Issue Reproduction

Minimal reproduction scripts demonstrating that OpenTelemetry traces are not being written to Unity Catalog tables in Databricks.

## 🔴 Issue Summary

Traces are **not appearing in Unity Catalog** even with:
- ✅ Correct OTel endpoint configuration
- ✅ OAuth token authentication
- ✅ Proper table schema (full OTel v1 spec)
- ✅ Client-side export succeeding

**Root Causes Identified:**
1. **Backend Storage**: OTel collector cannot write to S3 backing UC tables
2. **MLflow API**: `set_experiment_trace_location()` creates unqueryable tables

---

## 📊 Two Reproduction Scripts

### Script 1: Manual Table Creation (Recommended First)

**File:** `repro-otel-tracing-issue.py`

Creates UC tables manually with SQL, demonstrates backend storage issues.

```bash
# Install dependencies
pip install opentelemetry-api opentelemetry-sdk \
            opentelemetry-exporter-otlp-proto-http \
            databricks-sdk

# Authenticate
databricks auth login --profile dogfood

# Run
python repro-otel-tracing-issue.py
```

**What it shows:**
- ✅ Tables created with full OTel v1 schema
- ✅ Tables are queryable
- ✅ OTel export completes without client-side errors
- ❌ **Traces don't appear** → S3 "NOT_FOUND" errors when querying

**Conclusion:** Backend OTel collector cannot write to S3 storage.

---

### Script 2: MLflow API Creation

**File:** `repro-otel-with-mlflow-api.py`

Uses official `set_experiment_trace_location()` API, demonstrates MLflow API issues.

```bash
# Install dependencies (includes MLflow)
pip install 'mlflow[databricks]>=3.9.0' \
            opentelemetry-api opentelemetry-sdk \
            opentelemetry-exporter-otlp-proto-http \
            databricks-sdk

# Authenticate
databricks auth login --profile dogfood

# Run
python repro-otel-with-mlflow-api.py
```

**What it shows:**
- ✅ MLflow API creates tables (eventually)
- ❌ **API times out** after 60s
- ❌ **Tables have schema errors** → "Incomplete complex type"
- ❌ **Tables not queryable** despite having correct fields

**Conclusion:** MLflow public preview API has bugs.

---

## 🔍 What Both Scripts Test

1. **Authentication**: OAuth tokens from `databricks auth token` (PAT tokens cause 401s)
2. **Table Schema**: Complete OTel v1 schema with all required fields
3. **OTel Export**: Uses official Python OpenTelemetry SDK
4. **Verification**: Queries UC tables to check if traces appeared

---

## ✅ Expected Results (When Working)

```
✅ Got OAuth token
✅ Table created/verified
✅ OTel exporter configured
✅ Span created and exported
✅ Flush completed
✅ Trace found in UC table → SUCCESS!
```

---

## ❌ Actual Results (Current Behavior)

### Script 1 Output:
```
✅ Got OAuth token (expires in 3600s)
✅ Table created: main.agent_traces.otel_repro_test
✅ OTel exporter configured
✅ Span created: otel-repro-test-span
✅ Flush completed (no client-side errors)
⏳ Waiting 15 seconds for OTel collector to write to UC...
❌ Query failed: NOT_FOUND: Not Found () at file-scan-node-base.cc:455
```

**Translation:** Table exists in metastore, but OTel collector can't write data files to S3.

### Script 2 Output:
```
✅ Got OAuth token
✅ Created experiment
⚠️  API call timed out after 60s
✅ Table exists despite timeout
✅ All required fields present
✅ Flush completed (no client-side errors)
❌ Query failed: Incomplete complex type
```

**Translation:** MLflow API creates tables but they have schema corruption.

---

## 🐛 Technical Details

### Authentication Requirements

**CRITICAL:** The OTel collector requires **OAuth tokens**, not PAT tokens.

```python
# ✅ CORRECT - OAuth token (works)
import subprocess, json
result = subprocess.run(["databricks", "auth", "token", "--profile", "dogfood"],
                       capture_output=True, text=True)
token = json.loads(result.stdout)["access_token"]

# ❌ WRONG - PAT token (401 errors)
token = os.environ["DATABRICKS_TOKEN"]
```

### Schema Validation

The OTel collector **validates table schema** before writing. Missing optional fields cause rejection:

```
ERROR: Schema validation error:
  Field "flags" found in proto but not in table schema
  Field "dropped_attributes_count" found in proto but not in table schema
  Field "events" found in proto but not in table schema
  ...
```

Both scripts create tables with the **complete OTel v1 schema** (20+ fields) to avoid this.

### Storage Issues

Even with correct schema and auth, queries fail:

```sql
SELECT * FROM main.agent_traces.otel_spans_full;
-- Error: NOT_FOUND: Not Found () at file-scan-node-base.cc:455
```

This indicates the OTel collector backend cannot write Parquet files to the S3 bucket backing the UC tables.

---

## 📋 Questions for Team

### For OTel Collector Backend Team:

1. **S3 Permissions**: Does the OTel collector service principal have write permissions to the S3 buckets backing `main.agent_traces.*` tables in dogfood workspace?

2. **Public Preview Status**: Is "OpenTelemetry on Databricks" public preview fully enabled in e2-dogfood.staging.cloud.databricks.com?

3. **Error Visibility**: Should clients receive errors when backend writes fail? Currently failures are silent.

### For MLflow Team:

4. **API Timeout**: Why does `set_experiment_trace_location()` consistently take >60s?

5. **Schema Corruption**: Why do tables created by the API have "Incomplete complex type" errors that prevent queries?

6. **Error Handling**: Why does the API throw "INVALID_ARGUMENT: Inline disposition only supports ARROW_STREAM format" but still create tables?

---

## 🌍 Environment

- **Workspace**: `e2-dogfood.staging.cloud.databricks.com`
- **Profile**: `dogfood`
- **Region**: `us-west-2`
- **Catalog**: `main`
- **Schema**: `agent_traces`
- **Experiment ID**: `2610606164206831`

---

## 📖 Additional Documentation

See `TRACING_STATUS.md` for complete investigation details including:
- All fixes attempted
- OAuth token authentication solution
- Schema validation findings
- Timeline of investigation

---

## 🧹 Cleanup

After running the scripts:

```bash
# Script 1 cleanup
databricks sql --profile dogfood "DROP TABLE main.agent_traces.otel_repro_test"

# Script 2 cleanup
databricks sql --profile dogfood "
DROP TABLE main.agent_traces.mlflow_experiment_trace_otel_spans;
DROP TABLE main.agent_traces.mlflow_experiment_trace_otel_logs;
DROP TABLE main.agent_traces.mlflow_experiment_trace_otel_metrics;
"
```

---

## 💬 Contact

For questions about these reproduction scripts, contact:
- **Author**: Sid Murching (sid.murching@databricks.com)
- **Date**: 2026-02-17
- **Status**: Blocked on backend infrastructure

---

## 📄 License

These scripts are for internal Databricks debugging purposes.
