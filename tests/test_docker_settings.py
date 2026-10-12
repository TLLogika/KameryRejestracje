import importlib.util
import json
from pathlib import Path
import stat


spec=importlib.util.spec_from_file_location('configure_docker',Path(__file__).resolve().parent.parent/'scripts/configure_docker.py')
configure=importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


def test_private_configuration_preserves_existing_key(tmp_path,monkeypatch):
    monkeypatch.setattr(configure,'ROOT',tmp_path)
    monkeypatch.setenv('PANEL_BIND_IP','192.0.2.7')
    monkeypatch.setenv('PANEL_PORT','10000')
    monkeypatch.delenv('CODEX_PROXY_CERT',raising=False)
    private=tmp_path/'secret'
    private.mkdir()
    key=private/'integration.key'
    key.write_text('test-only-shared-key-'*3+'\n')
    before=key.read_text()
    configure.main()
    assert key.read_text()==before
    for path in (key,tmp_path/'dsecret/docker.env',tmp_path/'dsecret/compose.usb.json'):
        assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert stat.S_IMODE((tmp_path/'dsecret').stat().st_mode)==0o700
    assert 'PANEL_BIND_IP=192.0.2.7' in (tmp_path/'dsecret/docker.env').read_text()
    config=json.loads((tmp_path/'dsecret/compose.usb.json').read_text())
    assert 'privileged' not in config['services']['panel']


def test_invalid_port_does_not_create_deployment_files(tmp_path,monkeypatch):
    monkeypatch.setattr(configure,'ROOT',tmp_path)
    monkeypatch.setenv('PANEL_BIND_IP','192.0.2.7')
    monkeypatch.setenv('PANEL_PORT','70000')
    import pytest
    with pytest.raises(ValueError):
        configure.main()
    assert not (tmp_path/'dsecret/docker.env').exists()
