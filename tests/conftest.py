import pytest

from pendant_recorder.paths import Paths


@pytest.fixture
def root(tmp_path):
    return Paths(tmp_path / "Pendant")
