import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("inherited", [None, "0"])
def test_transcribe_import_sets_hf_hub_offline(inherited):
    env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
    if inherited is not None:
        env["HF_HUB_OFFLINE"] = inherited  # an exported opt-out must not survive the import
    out = subprocess.run(
        [sys.executable, "-c",
         "import lavalier.transcribe, huggingface_hub.constants as c; print(c.HF_HUB_OFFLINE)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "True"
