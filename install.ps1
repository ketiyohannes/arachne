# arachne installer for Windows. Run in an administrator PowerShell:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/ketiyohannes/arachne/main/install.ps1))) [-Join URL]
# Installs Tailscale, uv and Node.js if missing, then arachne, then runs `arachne setup`.
param([string]$Join = "", [string[]]$Key = @(), [switch]$NoDesktop)

$ErrorActionPreference = "Stop"
$Repo = "git+https://github.com/ketiyohannes/arachne"

function Say($Message) { Write-Host "`n==> $Message" }
function Has($Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.local\bin"
}

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    Write-Host "Please run this in an administrator PowerShell (needed to turn on the SSH server)."
    exit 1
}

if (-not (Has tailscale) -and -not (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
    Say "Installing Tailscale"
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
}
if (-not (Has uv)) {
    Say "Installing uv"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}
if (-not $NoDesktop -and -not (Has npm)) {
    Say "Installing Node.js (for agent-desktop)"
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
}
Refresh-Path
if (Test-Path "$env:ProgramFiles\Tailscale") { $env:Path += ";$env:ProgramFiles\Tailscale" }

Say "Installing arachne"
uv tool install --force $Repo
Refresh-Path

Say "Setting up this device"
$setupArgs = @("setup")
if ($Join) { $setupArgs += @("--join", $Join) }
foreach ($k in $Key) { $setupArgs += @("--key", $k) }
if ($NoDesktop) { $setupArgs += "--no-desktop" }
& arachne @setupArgs
