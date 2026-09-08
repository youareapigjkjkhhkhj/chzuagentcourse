import pytest
import os

os.environ["NEBIUS_API_KEY"] = "test_key_for_testing"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/erp_simulation"
