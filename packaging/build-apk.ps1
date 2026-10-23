# =============================================================================
# build-apk.ps1  —  N7SIX HamClock  —  produce  n7six.HamClock.v7.6.1.apk
# =============================================================================
# End-to-end Android build on Windows:
#   1. Cross-compile the native HamClock web-server executable per ABI (NDK).
#   2. Stage each into app/src/main/jniLibs/<abi>/libhamclock.so (native lib).
#   3. Assemble a debug-signed release APK with Gradle.
#
# Prerequisites (set these, or let the script point you to them):
#   $env:ANDROID_NDK_HOME   e.g. C:\Users\sebue\hc-buildtools\android-ndk-r26d
#   Android SDK with platform 34 + build-tools 34.0.0 (cmdline-tools installed)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\build-apk.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build-apk.ps1 -Abis arm64-v8a
# =============================================================================
[CmdletBinding()]
param(
    [string[]]$Abis = @('arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86'),
    [string]$Repo = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock',
    [string]$Version = '7.6.2',
    [switch]$SkipNative
)
$ErrorActionPreference = 'Stop'

$android = Join-Path $Repo 'android'
$tools   = 'C:\Users\sebue\hc-buildtools'
$javaBin = Get-ChildItem (Join-Path $tools 'jdk') -Recurse -Filter java.exe -ErrorAction SilentlyContinue |
           Select-Object -First 1 | ForEach-Object { Split-Path $_.FullName }

Write-Output "=== N7SIX HamClock APK build ==="
Write-Output "Repo:    $Repo"
Write-Output "ABIs:    $($Abis -join ', ')"
Write-Output "Version: $Version"

# ---- 0. locate NDK ---------------------------------------------------------
if (-not $env:ANDROID_NDK_HOME) {
    $guess = Get-ChildItem $tools -Directory -Filter 'android-ndk-*' -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($guess) { $env:ANDROID_NDK_HOME = $guess.FullName }
}
if (-not $env:ANDROID_NDK_HOME -or -not (Test-Path $env:ANDROID_NDK_HOME)) {
    throw "ANDROID_NDK_HOME is not set / not found. Install the NDK, then re-run."
}
Write-Output "NDK:     $env:ANDROID_NDK_HOME"

# ---- 1. native executable per ABI -----------------------------------------
if (-not $SkipNative) {
    # Find a bash (Git-for-Windows ships one) to run the portable native script.
    $bash = (Get-Command bash -ErrorAction SilentlyContinue).Source
    if (-not $bash) {
        throw "bash not found on PATH (Git for Windows). Install it, or build natives manually."
    }
    foreach ($abi in $Abis) {
        Write-Output "----- native build: $abi -----"
        & $bash (Join-Path $Repo 'packaging\build-apk-native.sh') $abi
        if ($LASTEXITCODE -ne 0) { throw "Native build failed for $abi (exit $LASTEXITCODE)" }
    }
} else {
    Write-Output "(skipping native build)"
}

# ---- 2. verify staged native libs -----------------------------------------
foreach ($abi in $Abis) {
    $bin = Join-Path $Repo "android\app\src\main\jniLibs\$abi\libhamclock.so"
    if (-not (Test-Path $bin)) { throw "Missing staged binary: $bin" }
    Write-Output ("staged: {0}  ({1:N1} MB)" -f $bin, ((Get-Item $bin).Length/1MB))
}

# ---- 3. Gradle assemble ----------------------------------------------------
$gradlew = Join-Path $android 'gradlew.bat'
if (-not (Test-Path $gradlew)) { throw "gradlew.bat not found at $gradlew" }

if ($env:ANDROID_HOME) { Write-Output "SDK:     $env:ANDROID_HOME" }
else { Write-Output "WARN: ANDROID_HOME not set; Gradle needs it to find the SDK." }

# Remove any previous release APKs first: gradlew.bat can fail to propagate a
# non-zero exit code, so we must never accept a leftover APK as proof of success.
$apkOutDir = Join-Path $android 'app\build\outputs\apk\release'
Remove-Item (Join-Path $apkOutDir '*.apk') -ErrorAction SilentlyContinue
$buildStart = Get-Date

Write-Output "----- gradle assembleRelease -----"
Push-Location $android
try {
    & $gradlew assembleRelease --no-daemon --warning-mode summary
    $gradleExit = $LASTEXITCODE
} finally { Pop-Location }
Write-Output "gradle exit code: $gradleExit"
if ($gradleExit -ne 0) { throw "Gradle build failed (exit $gradleExit)" }

# ---- 4. collect + rename the APK ------------------------------------------
$apk = Get-ChildItem (Join-Path $apkOutDir '*.apk') -ErrorAction SilentlyContinue |
       Sort-Object Length -Descending | Select-Object -First 1
if (-not $apk) { throw "No APK produced under app\build\outputs\apk\release" }
if ($apk.LastWriteTime -lt $buildStart) {
    throw ("APK is stale (built {0}, before gradle started {1}) - gradle did not produce it." -f `
        $apk.LastWriteTime, $buildStart)
}

$outDir = Join-Path $Repo 'dist'
$null = New-Item -ItemType Directory -Path $outDir -Force
$final  = Join-Path $outDir "n7six.HamClock.v$Version.apk"
Copy-Item $apk.FullName $final -Force

Write-Output ""
Write-Output "============================================================"
Write-Output (" APK READY: {0}" -f $final)
Write-Output (" Size:      {0:N1} MB" -f ((Get-Item $final).Length/1MB))
Write-Output (" SHA256:    {0}" -f (Get-FileHash $final -Algorithm SHA256).Hash)
Write-Output "============================================================"
Write-Output "Install: adb install -r `"$final`""
