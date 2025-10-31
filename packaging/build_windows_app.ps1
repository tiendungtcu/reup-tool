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
$ChromeMetadataEndpoint = if ($env:CHROME_METADATA_URL) { $env:CHROME_METADATA_URL } else { 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json' }
$ChromeFallbackVersion = if ($env:CHROME_FALLBACK_VERSION) { $env:CHROME_FALLBACK_VERSION } else { '128.0.6613.137' }

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

$script:GetWixTool = {
    param([Parameter(Mandatory = $true)][string]$Name)
    $resolved = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $resolved) {
        return $resolved.Source
    }
    return $null
}

function Install-FFmpegBinaries {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationDir,
        [string]$DownloadUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    )

    $ffmpegExe = Join-Path $DestinationDir 'ffmpeg.exe'
    $ffprobeExe = Join-Path $DestinationDir 'ffprobe.exe'
    $ffplayExe = Join-Path $DestinationDir 'ffplay.exe'

    if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
        Write-Host 'FFmpeg binaries already present; skipping download.' -ForegroundColor DarkGray
        return
    }

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ('ffmpeg-' + [System.IO.Path]::GetRandomFileName() + '.zip')
    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) ('ffmpeg-' + [System.IO.Path]::GetRandomFileName())

    try {
        Write-Host "Downloading FFmpeg from $DownloadUrl" -ForegroundColor Cyan
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $tempZip -UseBasicParsing

        Write-Host 'Extracting FFmpeg archive...' -ForegroundColor Cyan
        Expand-Archive -LiteralPath $tempZip -DestinationPath $tempExtract -Force

        $ffmpegSource = Get-ChildItem -Path $tempExtract -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
        $ffprobeSource = Get-ChildItem -Path $tempExtract -Filter 'ffprobe.exe' -Recurse | Select-Object -First 1
        $ffplaySource = Get-ChildItem -Path $tempExtract -Filter 'ffplay.exe' -Recurse | Select-Object -First 1
        $licenseSource = Get-ChildItem -Path $tempExtract -Filter 'LICENSE.txt' -Recurse | Select-Object -First 1

        if (-not $ffmpegSource -or -not $ffprobeSource) {
            throw 'Failed to locate ffmpeg.exe or ffprobe.exe in the downloaded archive.'
        }

        Copy-Item $ffmpegSource.FullName $ffmpegExe -Force
        Copy-Item $ffprobeSource.FullName $ffprobeExe -Force

        if ($ffplaySource) {
            Copy-Item $ffplaySource.FullName $ffplayExe -Force
        }

        if ($licenseSource) {
            Copy-Item $licenseSource.FullName (Join-Path $DestinationDir 'FFMPEG-LICENSE.txt') -Force
        }

        Write-Host "FFmpeg binaries installed to $DestinationDir" -ForegroundColor Green
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempZip
        if (Test-Path $tempExtract) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tempExtract
        }
    }
}

function Install-NodeRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationDir,
        [string]$DownloadUrl,
        [string]$Version = '20.17.0'
    )

    $nodeExe = Join-Path $DestinationDir 'node.exe'
    if (Test-Path $nodeExe) {
        Write-Host 'Node.js runtime already present; skipping download.' -ForegroundColor DarkGray
        return
    }

    if (-not $DownloadUrl) {
        $DownloadUrl = "https://nodejs.org/dist/v$Version/node-v$Version-win-x64.zip"
    }

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ('node-' + [System.IO.Path]::GetRandomFileName() + '.zip')
    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) ('node-' + [System.IO.Path]::GetRandomFileName())

    try {
        Write-Host "Downloading Node.js from $DownloadUrl" -ForegroundColor Cyan
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $tempZip -UseBasicParsing

        Write-Host 'Extracting Node.js archive...' -ForegroundColor Cyan
        Expand-Archive -LiteralPath $tempZip -DestinationPath $tempExtract -Force

        $rootDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
        if (-not $rootDir) {
            throw 'Failed to locate extracted Node.js directory.'
        }

        Copy-Item -Path (Join-Path $rootDir.FullName '*') -Destination $DestinationDir -Recurse -Force

        Write-Host "Node.js runtime installed to $DestinationDir" -ForegroundColor Green
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempZip
        if (Test-Path $tempExtract) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tempExtract
        }
    }
}

function Install-Aria2Cli {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationDir,
        [string]$DownloadUrl,
        [string]$Version = '1.37.0'
    )

    $aria2Exe = Join-Path $DestinationDir 'aria2c.exe'
    if (Test-Path $aria2Exe) {
        Write-Host 'aria2 already present; skipping download.' -ForegroundColor DarkGray
        return
    }

    if (-not $DownloadUrl) {
        $DownloadUrl = "https://github.com/aria2/aria2/releases/download/release-$Version/aria2-$Version-win-64bit-build1.zip"
    }

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ('aria2-' + [System.IO.Path]::GetRandomFileName() + '.zip')
    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) ('aria2-' + [System.IO.Path]::GetRandomFileName())

    try {
        Write-Host "Downloading aria2 from $DownloadUrl" -ForegroundColor Cyan
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $tempZip -UseBasicParsing

        Write-Host 'Extracting aria2 archive...' -ForegroundColor Cyan
        Expand-Archive -LiteralPath $tempZip -DestinationPath $tempExtract -Force

        $rootDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
        if (-not $rootDir) {
            throw 'Failed to locate extracted aria2 directory.'
        }

        Copy-Item -Path (Join-Path $rootDir.FullName '*') -Destination $DestinationDir -Recurse -Force

        Write-Host "aria2 installed to $DestinationDir" -ForegroundColor Green
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempZip
        if (Test-Path $tempExtract) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tempExtract
        }
    }
}

function Get-ChromeDownloadInfo {
    param(
        [Parameter(Mandatory = $true)][string]$Platform
    )

    try {
        $response = Invoke-WebRequest -Uri $ChromeMetadataEndpoint -UseBasicParsing -TimeoutSec 30
        $content = $response.Content
        if (-not $content) {
            throw 'No response body returned.'
        }
        $data = $content | ConvertFrom-Json
    }
    catch {
        Write-Warning "Failed to retrieve Chrome for Testing metadata: $_"
        return $null
    }

    $channels = $data.channels
    if (-not $channels) {
        Write-Warning 'Chrome metadata missing channel information.'
        return $null
    }

    $stable = $channels.Stable
    if (-not $stable) {
        Write-Warning 'Chrome metadata missing Stable channel entry.'
        return $null
    }

    $downloads = $stable.downloads
    if (-not $downloads) {
        Write-Warning 'Chrome metadata missing download listings.'
        return $null
    }

    $chromeDownloads = $downloads.chrome
    if (-not $chromeDownloads) {
        Write-Warning 'Chrome metadata missing chrome download entries.'
        return $null
    }

    $download = $chromeDownloads | Where-Object { $_.platform -eq $Platform } | Select-Object -First 1
    if (-not $download) {
        Write-Warning "Chrome metadata does not include a download for platform '$Platform'."
        return $null
    }

    return [pscustomobject]@{
        Version = $stable.version
        Url     = $download.url
    }
}

function Resolve-ChromeDownload {
    param(
        [string]$Version,
        [string]$DownloadUrl,
        [string]$Platform = 'win64'
    )

    $result = [pscustomobject]@{
        Version = $null
        Url     = $null
        Source  = 'unspecified'
    }

    if ($DownloadUrl) {
        $result.Url = $DownloadUrl
        $result.Version = if ($Version) { $Version } else { 'custom' }
        $result.Source = 'explicit-url'
        return $result
    }

    $resolvedVersion = $Version
    if (-not $resolvedVersion -or $resolvedVersion -eq '' -or $resolvedVersion -ieq 'latest') {
        $info = Get-ChromeDownloadInfo -Platform $Platform
        if ($info) {
            $resolvedVersion = $info.Version
            $result.Url = $info.Url
            $result.Source = 'metadata'
        }
        else {
            Write-Warning 'Falling back to pinned Chrome for Testing version because metadata lookup failed.'
            $resolvedVersion = $ChromeFallbackVersion
        }
    }

    if (-not $result.Url) {
        if (-not $resolvedVersion) {
            Write-Warning 'Unable to determine Chrome version; skipping Chrome bundling.'
            return $result
        }

        $archiveName = "chrome-$Platform.zip"
        $result.Url = "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/$resolvedVersion/$Platform/$archiveName"
        $result.Source = 'fallback'
    }

    $result.Version = $resolvedVersion
    return $result
}

function Install-ChromeRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationDir,
        [string]$DownloadUrl,
        [string]$Version
    )

    $resolved = Resolve-ChromeDownload -Version $Version -DownloadUrl $DownloadUrl -Platform 'win64'
    $resolvedVersion = $resolved.Version
    $resolvedUrl = $resolved.Url

    if (-not $resolvedUrl) {
        Write-Warning 'Chrome runtime download URL could not be determined; skipping Chrome bundling.'
        return
    }

    $versionMarker = Join-Path $DestinationDir '.chrome-version'
    $chromeExe = Join-Path $DestinationDir 'chrome.exe'

    if ($resolvedVersion -and $resolvedVersion -ne 'custom') {
        if ((Test-Path $chromeExe) -and (Test-Path $versionMarker)) {
            try {
                $currentVersion = Get-Content -Path $versionMarker -ErrorAction Stop | Select-Object -First 1
            }
            catch {
                $currentVersion = $null
            }

            if ($currentVersion -and ($currentVersion.Trim()) -eq $resolvedVersion) {
                Write-Host "Chrome runtime $resolvedVersion already present; skipping download." -ForegroundColor DarkGray
                return
            }
        }
    }

    $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ('chrome-' + [System.IO.Path]::GetRandomFileName() + '.zip')
    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) ('chrome-' + [System.IO.Path]::GetRandomFileName())
    $stagingDir = Join-Path ([System.IO.Path]::GetTempPath()) ('chrome-' + [System.IO.Path]::GetRandomFileName() + '-staging')

    try {
        Write-Host "Downloading Chrome for Testing ($resolvedVersion) from $resolvedUrl" -ForegroundColor Cyan
        Invoke-WebRequest -Uri $resolvedUrl -OutFile $tempZip -UseBasicParsing

        Write-Host 'Extracting Chrome archive...' -ForegroundColor Cyan
        Expand-Archive -LiteralPath $tempZip -DestinationPath $tempExtract -Force

        $rootDir = Get-ChildItem -Path $tempExtract -Directory | Where-Object { $_.Name -match 'chrome-win64' } | Select-Object -First 1
        if (-not $rootDir) {
            throw 'Failed to locate extracted Chrome directory.'
        }

        New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
        Copy-Item -Path (Join-Path $rootDir.FullName '*') -Destination $stagingDir -Recurse -Force

        if (Test-Path $DestinationDir) {
            Remove-Item -Recurse -Force $DestinationDir
        }
        Move-Item -Path $stagingDir -Destination $DestinationDir

        $extractedExe = Get-ChildItem -Path $DestinationDir -Filter 'chrome.exe' -Recurse | Select-Object -First 1
        if ($extractedExe) {
            Copy-Item -Path $extractedExe.FullName -Destination $chromeExe -Force
        }

        Write-Host "Chrome runtime installed to $DestinationDir" -ForegroundColor Green

        if ($resolvedVersion -and $resolvedVersion -ne 'custom') {
            Set-Content -Path $versionMarker -Value $resolvedVersion -Encoding ASCII
        }
        elseif (Test-Path $versionMarker) {
            Remove-Item -Force -ErrorAction SilentlyContinue $versionMarker
        }
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tempZip
        if (Test-Path $tempExtract) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tempExtract
        }
        if (Test-Path $stagingDir) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stagingDir
        }
    }
}

function Sync-AssetToInternal {
    param(
        [Parameter(Mandatory = $true)][string]$AppRoot,
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$RelativeName
    )

    $internalRoot = Join-Path $AppRoot '_internal'
    if (-not (Test-Path $internalRoot)) {
        return
    }

    if (-not (Test-Path $SourcePath)) {
        return
    }

    $target = Join-Path $internalRoot $RelativeName
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
    }

    $item = Get-Item $SourcePath
    if ($item.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Copy-Item -Path (Join-Path $SourcePath '*') -Destination $target -Recurse -Force
    }
    else {
        $parent = Split-Path -Parent $target
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -Path $SourcePath -Destination $target -Force
    }
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

$AppOutputDir = Join-Path $DistDir 'AutoBot-GUI'
if (-not (Test-Path $AppOutputDir)) {
        Write-Warning "Application directory not found at $AppOutputDir; skipping archive and installer creation."
        return
}

# Ensure FFmpeg binaries are bundled for offline use.
$ffmpegDir = Join-Path $AppOutputDir 'ffmpeg'
$ffmpegUrl = if ($env:FFMPEG_DOWNLOAD_URL) { $env:FFMPEG_DOWNLOAD_URL } else { $null }
# if ($ffmpegUrl) {
#     Install-FFmpegBinaries -DestinationDir $ffmpegDir -DownloadUrl $ffmpegUrl
# } else {
#     Install-FFmpegBinaries -DestinationDir $ffmpegDir
# }

# Ensure Node.js runtime is bundled for signature generation.
$nodeDir = Join-Path $AppOutputDir 'node'
$nodeUrl = if ($env:NODE_DOWNLOAD_URL) { $env:NODE_DOWNLOAD_URL } else { $null }
$nodeVersion = if ($env:NODE_VERSION) { $env:NODE_VERSION } else { '20.17.0' }
Install-NodeRuntime -DestinationDir $nodeDir -DownloadUrl $nodeUrl -Version $nodeVersion

# Ensure aria2 CLI is bundled for accelerated downloads.
$aria2Dir = Join-Path $AppOutputDir 'aria2'
$aria2Url = if ($env:ARIA2_DOWNLOAD_URL) { $env:ARIA2_DOWNLOAD_URL } else { $null }
$aria2Version = if ($env:ARIA2_VERSION) { $env:ARIA2_VERSION } else { '1.37.0' }
Install-Aria2Cli -DestinationDir $aria2Dir -DownloadUrl $aria2Url -Version $aria2Version

# Ensure Chrome runtime is bundled for browser automation.
$chromeDir = Join-Path $AppOutputDir 'chrome'
$chromeUrl = if ($env:CHROME_DOWNLOAD_URL) { $env:CHROME_DOWNLOAD_URL } else { $null }
$chromeVersion = if ($env:CHROME_VERSION) { $env:CHROME_VERSION } else { $null }
Install-ChromeRuntime -DestinationDir $chromeDir -DownloadUrl $chromeUrl -Version $chromeVersion

# Mirror assets into the _internal directory for PyInstaller runtime access.
Sync-AssetToInternal -AppRoot $AppOutputDir -SourcePath $ffmpegDir -RelativeName 'ffmpeg'
Sync-AssetToInternal -AppRoot $AppOutputDir -SourcePath $aria2Dir -RelativeName 'aria2'
Sync-AssetToInternal -AppRoot $AppOutputDir -SourcePath $nodeDir -RelativeName 'node'
Sync-AssetToInternal -AppRoot $AppOutputDir -SourcePath $chromeDir -RelativeName 'chrome'

# Create ZIP archive for portable distribution.
$ZipName = if ($env:ZIP_NAME) { $env:ZIP_NAME } else { 'AutoBot-GUI.zip' }
$ZipPath = Join-Path $DistDir $ZipName
if (Test-Path $ZipPath) {
        Remove-Item -Force $ZipPath
}

Write-Host "Creating ZIP package at $ZipPath" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $AppOutputDir '*') -DestinationPath $ZipPath
Write-Host "ZIP package created at: $ZipPath" -ForegroundColor Green

# Attempt to produce an MSI installer using the WiX Toolset if available.
$HeatExe = & $script:GetWixTool 'heat.exe'
$CandleExe = & $script:GetWixTool 'candle.exe'
$LightExe = & $script:GetWixTool 'light.exe'

if (-not $HeatExe -or -not $CandleExe -or -not $LightExe) {
        Write-Warning 'WiX Toolset (heat.exe, candle.exe, light.exe) not found in PATH; skipping MSI creation.'
        return
}

$MsiName = if ($env:MSI_NAME) { $env:MSI_NAME } else { 'AutoBot-GUI.msi' }
$MsiPath = Join-Path $DistDir $MsiName
$MsiProductName = if ($env:MSI_PRODUCT_NAME) { $env:MSI_PRODUCT_NAME } else { 'AutoBot GUI' }
$MsiManufacturer = if ($env:MSI_MANUFACTURER) { $env:MSI_MANUFACTURER } else { 'AutoBot' }
$MsiVersion = if ($env:MSI_VERSION) { $env:MSI_VERSION } else { '1.0.0' }
$MsiUpgradeCode = if ($env:MSI_UPGRADE_CODE) { $env:MSI_UPGRADE_CODE } else { '0A1F42D7-3B67-4AF7-9C0D-DAED8D2BCB35' }

$WixWorkDir = Join-Path $DistDir '.wix-build'
if (Test-Path $WixWorkDir) {
        Remove-Item -Recurse -Force $WixWorkDir
}
New-Item -ItemType Directory -Path $WixWorkDir | Out-Null

$FragmentFile = Join-Path $WixWorkDir 'AppFiles.wxs'
$FragmentObj = Join-Path $WixWorkDir 'AppFiles.wixobj'
$ProductFile = Join-Path $WixWorkDir 'Product.wxs'
$ProductObj = Join-Path $WixWorkDir 'Product.wixobj'

Write-Host 'Harvesting application files for MSI...' -ForegroundColor Cyan
& $HeatExe dir $AppOutputDir -cg AutoBotGUIComponents -dr INSTALLDIR -sreg -srd -var var.SourceDir -out $FragmentFile | Out-Null
if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $WixWorkDir -ErrorAction SilentlyContinue
        throw 'WiX heat.exe failed to harvest application files.'
}

$ProductDefinition = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
    <Product Id="*" Name="$MsiProductName" Language="1033" Version="$MsiVersion" Manufacturer="$MsiManufacturer" UpgradeCode="$MsiUpgradeCode">
        <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
        <MajorUpgrade AllowDowngrades="no" DowngradeErrorMessage="A newer version of $MsiProductName is already installed." />
        <MediaTemplate EmbedCab="yes" />
        <Feature Id="MainFeature" Title="$MsiProductName" Level="1">
            <ComponentGroupRef Id="AutoBotGUIComponents" />
        </Feature>
    </Product>
    <Fragment>
        <Directory Id="TARGETDIR" Name="SourceDir">
            <Directory Id="ProgramFilesFolder">
                <Directory Id="INSTALLDIR" Name="$MsiProductName" />
            </Directory>
        </Directory>
    </Fragment>
</Wix>
"@

Set-Content -Path $ProductFile -Value $ProductDefinition -Encoding UTF8

Write-Host 'Compiling MSI sources...' -ForegroundColor Cyan
& $CandleExe -dSourceDir="$AppOutputDir" -o $FragmentObj $FragmentFile | Out-Null
if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $WixWorkDir -ErrorAction SilentlyContinue
        throw 'WiX candle.exe failed while compiling harvested fragment.'
}

& $CandleExe -dSourceDir="$AppOutputDir" -o $ProductObj $ProductFile | Out-Null
if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $WixWorkDir -ErrorAction SilentlyContinue
        throw 'WiX candle.exe failed while compiling product definition.'
}

Write-Host 'Linking MSI package...' -ForegroundColor Cyan
& $LightExe -o $MsiPath $ProductObj $FragmentObj | Out-Null
if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $WixWorkDir -ErrorAction SilentlyContinue
        throw 'WiX light.exe failed while producing the MSI.'
}

Remove-Item -Recurse -Force $WixWorkDir -ErrorAction SilentlyContinue
Write-Host "MSI package created at: $MsiPath" -ForegroundColor Green
