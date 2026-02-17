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

## 📊 Minimal Reproduction Scripts

Both scripts are **concise** (~120-280 lines) with clear assertions that **fail** when traces don't appear.

### Script 1: Manual Table Creation

**File:** `repro-otel-tracing-issue.py` (~280 lines)

Creates UC tables manually with SQL, demonstrates backend storage issues.

```bash
pip install -r requirements.txt
databricks auth login --profile dogfood
python repro-otel-tracing-issue.py
```

**Result:** `AssertionError: Traces not found in Unity Catalog table`
- ✅ Tables queryable
- ❌ Traces don't appear → S3 "NOT_FOUND" errors

**Conclusion:** Backend OTel collector cannot write to S3 storage.

---

### Script 2: MLflow API Creation (Simpler)

**File:** `repro-otel-with-mlflow-api.py` (~120 lines)

Uses official `set_experiment_trace_location()` API, demonstrates MLflow API issues.

```bash
pip install -r requirements.txt
databricks auth login --profile dogfood
python repro-otel-with-mlflow-api.py
```

**Result:** `AssertionError: Traces not found in Unity Catalog table`
- ⚠️ API may timeout (but tables still created)
- ❌ Tables have "Incomplete complex type" → not queryable
- ❌ Even if queryable, traces don't appear

**Conclusion:** MLflow API creates broken tables + backend storage issue.

---

## 🔍 What Scripts Test

1. **Setup**: Get OAuth token, create/verify UC tables
2. **Export**: Send test span via OTel SDK
3. **Verify**: Query UC table and **assert trace exists**
4. **Result**: `AssertionError` when traces don't appear

---

## ✅ Expected (When Working)

```python
✓ Setup complete
✓ Trace sent
✓ SUCCESS: Trace found in UC table!
```

## ❌ Actual (Current Behavior)

```python
✓ Setup complete
✓ Trace sent
✗ FAILED: Traces not found in UC table
   Query status: FAILED
   Error: NOT_FOUND: Not Found () / Incomplete complex type

AssertionError: Traces not found in Unity Catalog table
```

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
