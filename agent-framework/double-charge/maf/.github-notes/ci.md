# MAF-only CI notes

A future path-filtered workflow may run from this folder without importing another
app's automation:

```text
python -m pip install -e shared -e "agent-framework/double-charge/maf[dev]"
python -m pytest agent-framework/double-charge/maf/backend/tests
python agent-framework/double-charge/maf/evals/run.py
npm --prefix agent-framework/double-charge/maf/frontend ci
npm --prefix agent-framework/double-charge/maf/frontend test
npm --prefix agent-framework/double-charge/maf/frontend run build
```

The repository workflow itself is intentionally not created here because this
workstream is restricted to `maf/**`.

