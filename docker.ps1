param(
    [ValidateSet('up','down','restart','logs','ps','build')][string]$Command='up',
    [switch]$NoBuild,
    [switch]$Demo,
    [switch]$UsbBridge
)
$ErrorActionPreference='Stop'
$ProjectRoot=$PSScriptRoot
Set-Location $ProjectRoot
foreach ($Directory in @('data','dsecret','secret','logi')) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}
$Utf8=New-Object System.Text.UTF8Encoding($false)
$KeyPath=Join-Path $ProjectRoot 'secret/integration.key'
if (-not (Test-Path $KeyPath)) {
    $Bytes=New-Object byte[] 48
    $Random=[System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Random.GetBytes($Bytes) } finally { $Random.Dispose() }
    $Key=[Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    [IO.File]::WriteAllText($KeyPath,$Key+"`n",$Utf8)
}
$SettingsPath=Join-Path $ProjectRoot 'dsecret/docker-windows.env'
$BindAddress='127.0.0.1'
$PanelPort='10000'
if ($env:PANEL_BIND_IP) { $BindAddress=$env:PANEL_BIND_IP }
if ($env:PANEL_PORT) { $PanelPort=$env:PANEL_PORT }
$ParsedAddress=$null
if (-not [Net.IPAddress]::TryParse($BindAddress,[ref]$ParsedAddress)) { throw 'Invalid PANEL_BIND_IP' }
if ($ParsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'PANEL_BIND_IP must be IPv4.' }
if ([int]$PanelPort -lt 1 -or [int]$PanelPort -gt 65535) { throw 'Invalid PANEL_PORT' }
$BridgeUrl=''
if ($UsbBridge) {
    if (-not (Test-Path 'dsecret/usb-bridge.key')) { throw 'Start windows-usb.ps1 first to create the USB bridge key.' }
    $BridgeUrl='http://host.docker.internal:10001'
}
$Content="APP_UID=1000`nAPP_GID=1000`nPERMISSIONS_MODE=portable`nPANEL_BIND_IP=$BindAddress`nPANEL_PORT=$PanelPort`nUSB_BRIDGE_URL=$BridgeUrl`n"
[IO.File]::WriteAllText($SettingsPath,$Content,$Utf8)
$Compose=@('compose','--env-file',$SettingsPath,'-f','compose.yaml')
if ($Demo) { $Compose+=@('-f','compose.demo.yaml') }
$Operation=@($Command)
if ($Command -eq 'up') {
    $Operation+=@('-d','--wait','--wait-timeout','120')
    if (-not $NoBuild) { $Operation+='--build' }
}
if ($Command -eq 'logs') { $Operation+=@('--tail','50','panel') }
& docker @Compose @Operation
if ($LASTEXITCODE -ne 0) { throw "Docker exited with code $LASTEXITCODE" }
