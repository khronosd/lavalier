import os
import subprocess
import sys


def test_transcribe_import_sets_hf_hub_offline():
    env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import pendant_recorder.transcribe, huggingface_hub.constants as c; print(c.HF_HUB_OFFLINE)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "True"
