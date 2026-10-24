from pathlib import Path

import pytest

from lavalier.config import Config, load_config, save_config
from lavalier.paths import Paths
from lavalier.settings import EDITABLE, SettingsError, apply, read_settings


def test_read_settings_exposes_editable_fields_and_facts(cfg, root):
    s = read_settings(cfg, root)
    assert s["retention_days"] == 14 and s["appearance"] == "system" and s["readonly"]["whisper_model"].startswith("mlx-community/")
    assert all(f in s for f in EDITABLE)
    assert s["readonly"]["state_root"] == str(root.root) and s["readonly"]["bundle_id"] == "io.github.khronosd.lavalier"


def test_bundle_id_matches_the_bundle_builder():
    build_app = pytest.importorskip("bundle.build_app")
    assert read_settings(Config(), Paths(Path("/x")))["readonly"]["bundle_id"] == build_app.BUNDLE_ID


def test_apply_validates_and_saves(cfg, tmp_path):
    new = apply(cfg, {"retention_days": 30, "appearance": "dark"}, tmp_path / "c.toml")
    assert new.retention_days == 30 and load_config(tmp_path / "c.toml").appearance == "dark"


@pytest.mark.parametrize("patch,field", [
    ({"noise_mean_db": -30}, "noise_mean_db"),
    ({"appearance": "sepia"}, "appearance"),
    ({"retention_days": -1}, "retention_days"),
    ({"poll_interval_s": 5}, "poll_interval_s"),
    ({"window_size": "big"}, "window_size"),
    ({"retention_days": "14"}, "retention_days"),
    ({"retention_days": True}, "retention_days"),
    ({"require_firmware": 3}, "require_firmware"),
    ({"retention_days": 36501}, "retention_days"),
    ({"drain_pages_threshold": 0}, "drain_pages_threshold"),
    ({"drain_after_hours": -1}, "drain_after_hours"),
    ({"whisper_language": "english"}, "whisper_language"),
    ({"whisper_language": "E"}, "whisper_language"),
    ({"whisper_language": "en\n"}, "whisper_language"),
    ({"whisper_language": ""}, "whisper_language"),
])
def test_apply_rejects_bad_patches_naming_the_field(cfg, tmp_path, patch, field):
    with pytest.raises(SettingsError, match=field) as e:
        apply(cfg, patch, tmp_path / "c.toml")
    assert e.value.field == field
    assert not (tmp_path / "c.toml").exists()


def test_apply_validates_everything_before_writing(cfg, tmp_path):
    path = tmp_path / "c.toml"
    with pytest.raises(SettingsError, match="poll_interval_s"):
        apply(cfg, {"retention_days": 30, "poll_interval_s": 5}, path)
    assert not path.exists() and cfg.retention_days == 14


def test_apply_keeps_other_fields_and_does_not_mutate_input(cfg, tmp_path):
    cfg2 = Config(pendant_address="X", noise_mean_db=-33.0)
    new = apply(cfg2, {"retention_days": 0}, tmp_path / "c.toml")
    assert new.pendant_address == "X" and new.noise_mean_db == -33.0 and cfg2.retention_days == 14


def test_app_reload_config_picks_up_a_saved_setting(app_env):
    from tests.fake_pendant import FakePendant
    app = app_env(FakePendant())
    assert app.cfg.retention_days == 14
    apply(app.cfg, {"retention_days": 21}, app.paths.config)
    assert app.cfg.retention_days == 14
    app.reload_config()
    assert app.cfg.retention_days == 21


def test_reload_config_survives_a_corrupt_file(app_env, caplog):
    from tests.fake_pendant import FakePendant
    app = app_env(FakePendant())
    assert app.reload_config() is True
    before = app.cfg
    app.paths.config.write_text('retention_days = "x"\n')
    with caplog.at_level("ERROR"):
        assert app.reload_config() is False
    assert app.cfg is before
    assert "retention_days" in caplog.text


def test_apply_patches_the_file_on_disk_not_the_callers_copy(tmp_path):
    path = tmp_path / "c.toml"
    save_config(Config(retention_days=21, appearance="dark"), path)
    stale = Config()  # loaded before the other writer saved
    new = apply(stale, {"window_size": "1280x800"}, path)
    saved = load_config(path)
    assert (saved.retention_days, saved.appearance, saved.window_size) == (21, "dark", "1280x800")
    assert new == saved


def test_apply_refuses_to_overwrite_an_unreadable_file(tmp_path):
    from lavalier.config import ConfigError
    path = tmp_path / "c.toml"
    path.write_text('retention_days = "x"\n')
    with pytest.raises(ConfigError):
        apply(Config(), {"window_size": "1280x800"}, path)
    assert path.read_text() == 'retention_days = "x"\n'


@pytest.mark.parametrize("patch", [
    {"retention_days": 0}, {"retention_days": 36500}, {"drain_pages_threshold": 1}, {"drain_after_hours": 0},
    {"whisper_language": "en"}, {"whisper_language": "yue"},
])
def test_apply_accepts_values_on_the_bounds(cfg, tmp_path, patch):
    assert apply(cfg, patch, tmp_path / "c.toml")
