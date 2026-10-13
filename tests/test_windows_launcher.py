import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parent.parent


def powershell():
    native=Path('/snap/powershell/current/opt/powershell/pwsh')
    return str(native) if native.is_file() else shutil.which('pwsh')


def test_windows_launcher_preserves_key_generates_portable_env_and_calls_compose(tmp_path):
    executable=powershell()
    if not executable:pytest.skip('PowerShell is not installed')
    shutil.copyfile(ROOT/'docker.ps1',tmp_path/'docker.ps1')
    private=tmp_path/'dsecret';private.mkdir()
    (private/'usb-bridge.key').write_text('test-usb-bridge-key-'*3)
    secret=tmp_path/'secret';secret.mkdir()
    (secret/'integration.key').write_text('existing-test-integration-key-'*2)
    driver=tmp_path/'test.ps1'
    driver.write_text('''$ErrorActionPreference='Stop'
function global:docker {
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'docker-arguments.json'),(ConvertTo-Json @($args)))
    $global:LASTEXITCODE=0
}
& (Join-Path $PSScriptRoot 'docker.ps1') -NoBuild -UsbBridge
''')
    subprocess.run([executable,'-NoProfile','-NonInteractive','-File',str(driver)],check=True,capture_output=True,text=True)
    env=(private/'docker-windows.env').read_text()
    assert not env.startswith('\ufeff')
    assert 'PERMISSIONS_MODE=portable' in env and 'USB_BRIDGE_URL=http://host.docker.internal:10001' in env
    assert 'PANEL_BIND_IP=127.0.0.1' in env
    assert (secret/'integration.key').read_text()=='existing-test-integration-key-'*2
    args=json.loads((tmp_path/'docker-arguments.json').read_text())
    assert 'up' in args and '-d' in args and '--wait' in args and '--build' not in args
    assert not any('integration-key' in item for item in args)
