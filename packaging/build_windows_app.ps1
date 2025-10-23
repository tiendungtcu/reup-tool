#!/usr/bin/env pwsh
<#!
.SYNOPSIS
    Build a standalone AutoBot GUI bundle for Windows using PyInstaller.

.DESCRIPTION
    Creates an isolated virtual environment, installs the required
    dependencies, runs PyInstaller with the existing spec file, and
    verifies that bundled assets (including TikTok signature helpers)
    are copied into the resulting dist folder.

.NOTES
    Run this script from PowerShell on a Windows machine that has
    Python 3.11 or newer installed. Administrator privileges are not
    required.

.EXAMPLE
    PS> ./packaging/build_windows_app.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptRoot '..')
Set-Location $ProjectRoot

$SpecFile = Join-Path $ProjectRoot 'packaging/autobot_gui.spec'
$DistDir = Join-Path $ProjectRoot 'dist'
$BuildVenv = if ($env:BUILD_VENV) { $env:BUILD_VENV } else { Join-Path $ProjectRoot '.build-venv-win' }

function Resolve-Python {
    param(
        [string[]]$Candidates = @('python', 'python3.13', 'python3.12', 'python3.11')
    )

    foreach ($candidate in $Candidates) {
        $resolved = (Get-Command $candidate -ErrorAction SilentlyContinue)
        if ($null -ne $resolved) {
            $pythonVersionProbe = @"
import sys
if sys.version_info >= (3, 11):
    print(sys.executable)
"@
            $versionInfo = & $resolved.Source -c $pythonVersionProbe
            if ($LASTEXITCODE -eq 0 -and $versionInfo) {
                return $versionInfo.Trim()
            }
        }
    }

    throw "Python 3.11+ executable not found. Install a supported Python version."
}

$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { Resolve-Python }

if (Test-Path $BuildVenv) {
    $venvVersionProbe = @"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
"@
    & "$BuildVenv/Scripts/python.exe" -c $venvVersionProbe
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Refreshing build virtual environment to match Python $Python" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $BuildVenv
    }
}

if (-not (Test-Path $BuildVenv)) {
    Write-Host "Creating build virtual environment at $BuildVenv" -ForegroundColor Cyan
    & $Python -m venv $BuildVenv
}

$EnvPython = Join-Path $BuildVenv 'Scripts/python.exe'

Write-Host 'Installing build dependencies...' -ForegroundColor Cyan
& $EnvPython -m pip install --upgrade pip
& $EnvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
& $EnvPython -m pip install -r (Join-Path $ProjectRoot 'requirements_gui.txt')
& $EnvPython -m pip install pyinstaller

Write-Host 'Running PyInstaller...' -ForegroundColor Cyan
& $EnvPython -m PyInstaller $SpecFile --clean --noconfirm

if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}

# Ensure TikTok signature assets exist in the output folder (redundant with spec, but double-check).
$SignatureSource = Join-Path $ProjectRoot 'tiktok_uploader/tiktok-signature'
if (Test-Path $SignatureSource) {
    $InternalSigTarget = Join-Path $DistDir 'AutoBot-GUI/_internal/tiktok_uploader/tiktok-signature'
    if (-not (Test-Path $InternalSigTarget)) {
        New-Item -ItemType Directory -Force -Path $InternalSigTarget | Out-Null
        Copy-Item -Path (Join-Path $SignatureSource '*') -Destination $InternalSigTarget -Recurse -Force
    }

    $TopLevelTarget = Join-Path $DistDir 'AutoBot-GUI/tiktok_uploader/tiktok-signature'
    if (-not (Test-Path $TopLevelTarget)) {
        New-Item -ItemType Directory -Force -Path $TopLevelTarget | Out-Null
        Copy-Item -Path (Join-Path $SignatureSource '*') -Destination $TopLevelTarget -Recurse -Force
    }
}

Write-Host ''
Write-Host '✅ Build complete.' -ForegroundColor Green
Write-Host "Artifacts available in: $DistDir" -ForegroundColor Green
