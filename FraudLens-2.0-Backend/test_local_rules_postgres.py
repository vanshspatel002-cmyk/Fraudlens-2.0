"""Opt-in disposable PostgreSQL local-mode transactions, never Gemini."""
from test_postgres import client,pg_schema,pytestmark
from test_partial_review import pipeline
from test_local_rules_mode import test_local_pipeline_never_initializes_provider_and_freezes_one_contract
