import pytest

from lavalier.config import Config, load_config, save_config
from lavalier.settings import EDITABLE, SettingsError, apply, read_settings


def test_read_settings_exposes_editable_fields_and_facts(cfg, root):
    s = read_settings(cfg)
    assert s["retention_days"] == 14 and s["appearance"] == "system" and s["readonly"]["whisper_model"].startswith("mlx-community/")
    assert all(f in s for f in EDITABLE)
    assert s["readonly"]["state_root"] and s["readonly"]["bundle_id"] == "io.github.khronosd.lavalier"


def test_bundle_id_matches_the_bundle_builder():
    build_app = pytest.importorskip("bundle.build_app")
    assert read_settings(Config())["readonly"]["bundle_id"] == build_app.BUNDLE_ID


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
])
def test_apply_rejects_bad_patches_naming_the_field(cfg, tmp_path, patch, field):
    with pytest.raises(SettingsError, match=field):
        apply(cfg, patch, tmp_path / "c.toml")
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
