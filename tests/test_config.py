from dataclasses import replace

import pytest

from lavalier.config import Config, ConfigError, load_config, save_config
from lavalier.paths import Paths


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.retention_days == 14 and cfg.conversation_gap_s == 120 and cfg.whisper_model == "mlx-community/whisper-large-v3-turbo"


def test_round_trip_and_unknown_keys(tmp_path):
    p = tmp_path / "config.toml"
    save_config(Config(retention_days=0, pendant_address="501D2009-1F91-FCCB-CD97-B1F23A35FB72"), p)
    p.write_text(p.read_text() + "\nfuture_key = 1\n")
    cfg = load_config(p)
    assert cfg.retention_days == 0 and cfg.pendant_address.startswith("501D2009")


def test_wrong_type_raises(tmp_path):
    p = tmp_path / "config.toml"; p.write_text('retention_days = "soon"\n')
    with pytest.raises(ConfigError): load_config(p)


def test_paths_layout(tmp_path):
    ps = Paths(tmp_path / "Pendant"); ps.ensure()
    assert ps.db == tmp_path / "Pendant" / "state.sqlite" and ps.audio.is_dir() and ps.days.is_dir() and ps.captures.is_dir() and ps.logs.is_dir()


def test_device_defaults_and_toml_round_trip(tmp_path):
    cfg = Config()
    assert (cfg.poll_interval_s, cfg.scan_timeout_s, cfg.drain_idle_timeout_s) == (600, 8.0, 5.0)
    assert (cfg.drain_pages_threshold, cfg.drain_after_hours, cfg.fsync_every_pages, cfg.require_firmware) == (1000, 24, 100, "")
    save_config(replace(cfg, require_firmware="1.1.3", poll_interval_s=300), tmp_path / "c.toml")
    loaded = load_config(tmp_path / "c.toml")
    assert (loaded.require_firmware, loaded.poll_interval_s) == ("1.1.3", 300)


def test_appearance_and_window_size_defaults_and_type_check(tmp_path):
    assert load_config(tmp_path / "none.toml").appearance == "system"
    assert load_config(tmp_path / "none.toml").window_size == "1120x720"
    p = tmp_path / "config.toml"
    p.write_text("appearance = 3\n")
    with pytest.raises(ConfigError, match="appearance"):
        load_config(p)


def test_save_config_keeps_unknown_keys_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("future_key = 1\nretention_days = 3\n")
    assert load_config(p).retention_days == 3
    save_config(Config(retention_days=9), p)
    assert load_config(p).retention_days == 9
    assert "future_key = 1" in p.read_text()
    assert [f.name for f in tmp_path.iterdir()] == ["config.toml"]


def test_save_config_refuses_to_overwrite_an_unreadable_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("not [valid")
    with pytest.raises(ConfigError):
        save_config(Config(), p)
    assert p.read_text() == "not [valid"
