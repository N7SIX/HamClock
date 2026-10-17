# =============================================================================
# setup-android-sdk.ps1  —  install cmdline-tools, SDK packages, and the NDK
# =============================================================================
# Installs a minimal Android build toolchain into C:\Users\sebue\hc-buildtools:
#   cmdline-tools, platform-tools, platforms;android-34, build-tools;34.0.0, NDK
# and prints the ANDROID_HOME / ANDROID_NDK_HOME values to export.
#
# NOTE: this downloads several hundred MB (the NDK alone is ~1 GB). On a slow
# link it can take a long time. Run once; afterwards build-apk.ps1 just uses it.
# =============================================================================
[CmdletBinding()]
param(
    [string]$Tools = 'C:\Users\sebue\hc-buildtools',
    [string]$SdkApi = '34',
    [string]$BuildTools = '34.0.0',
    [string]$Ndk = '26.3.11579264'
)
$ErrorActionPreference = 'Stop'

$sdk = Join-Path $Tools 'android-sdk'
$clt = Join-Path $sdk 'cmdline-tools\latest'
$sdkman = Join-Path $clt 'bin\sdkmanager.bat'
$javaBin = Get-ChildItem (Join-Path $Tools 'jdk') -Recurse -Filter java.exe -ErrorAction SilentlyContinue |
           Select-Object -First 1 | ForEach-Object { Split-Path $_.FullName }

function Get-CmdlineTools {
    if (Test-Path $sdkman) { Write-Output 'cmdline-tools already present'; return }
    $zip = Join-Path $Tools 'cmdline-tools.zip'
    $url = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
    if (-not (Test-Path $zip)) {
        Write-Output "Downloading cmdline-tools -> $zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 600
    }
    Write-Output 'Extracting cmdline-tools...'
    $tmp = Join-Path $Tools 'clt-extract'
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Path (Split-Path $clt) -Force | Out-Null
    Move-Item (Join-Path $tmp 'cmdline-tools') $clt -Force
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Get-CmdlineTools

# Accept licenses + install packages.
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
if ($javaBin) { $env:PATH = "$javaBin;$env:PATH" }

Write-Output 'Accepting licenses...'
$licOk = $false
for ($i = 0; $i -lt 8; $i++) {
    'y' | & $sdkman --licenses > $null 2>&1
    if ($LASTEXITCODE -eq 0) { $licOk = $true; break }
}
if (-not $licOk) { Write-Output 'WARN: license acceptance did not fully succeed (continuing).' }

Write-Output "Installing platform-tools, platforms;android-$SdkApi, build-tools;$BuildTools, NDK $Ndk ..."
& $sdkman "platform-tools" "platforms;android-$SdkApi" "build-tools;$BuildTools" "ndk;$Ndk"
if ($LASTEXITCODE -ne 0) { throw "sdkmanager install failed (exit $LASTEXITCODE)" }

$ndkHome = Get-ChildItem (Join-Path $sdk 'ndk') -Directory -ErrorAction SilentlyContinue |
           Sort-Object Name -Descending | Select-Object -First 1

Write-Output ''
Write-Output '============================================================'
Write-Output ' Android toolchain ready.'
Write-Output "   SDK:  $sdk"
if ($ndkHome) { Write-Output "   NDK:  $($ndkHome.FullName)" }
Write-Output ''
Write-Output ' Export these before building the APK:'
Write-Output "   `$env:ANDROID_HOME     = `"$sdk`""
if ($ndkHome) { Write-Output "   `$env:ANDROID_NDK_HOME = `"$($ndkHome.FullName)`"" }
Write-Output '============================================================'
