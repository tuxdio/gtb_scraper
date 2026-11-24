"""Shared pytest setup: add the project root to sys.path and provide a fixture loader."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


@pytest.fixture
def load_fixture():
    """Load a raw page from tests/fixtures (the site uses GBK encoding)."""
    def _load(name: str) -> str:
        with open(os.path.join(FIXTURES, name), 'rb') as f:
            return f.read().decode('gbk', 'ignore')
    return _load
