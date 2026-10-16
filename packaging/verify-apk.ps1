# =============================================================================
# verify-apk.ps1  —  N7SIX HamClock  —  ground-truth verification of build state
# =============================================================================
$ErrorActionPreference = 'Continue'
$Repo  = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
$Tools = 'C:\Users\sebue\hc-buildtools'

Write-Output '=== 1. build.gradle raw state ==='
$bg = Join-Path $Repo 'android\app\build.gradle'
$bytes = [IO.File]::ReadAllBytes($bg)
Write-Output ("Length: {0} bytes" -f $bytes.Length)
Write-Output ("First 8 bytes: {0}" -f (($bytes[0..7] | ForEach-Object { $_.ToString('X2') }) -join ' '))
$text = [Text.Encoding]::UTF8.GetString($bytes)
$nl   = ($text.ToCharArray() | Where-Object { $_ -eq "`n" }).Count
$cr   = ($text.ToCharArray() | Where-Object { $_ -eq "`r" }).Count
Write-Output ("Newlines: $nl   CRs: $cr")
Write-Output ("LastWriteTime: {0}" -f (Get-Item $bg).LastWriteTime)
Write-Output ("Starts with: [{0}]" -f $text.Substring(0, [Math]::Min(40, $text.Length)))

Write-Output ''
Write-Output '=== 2. gradle output APK ==='
$oa = Join-Path $Repo 'android\app\build\outputs\apk\release\app-release.apk'
if (Test-Path $oa) {
    $oi = Get-Item $oa
    Write-Output ("app-release.apk: {0} bytes, {1}" -f $oi.Length, $oi.LastWriteTime)
    Write-Output ("SHA256: {0}" -f (Get-FileHash $oa -Algorithm SHA256).Hash)
} else { Write-Output 'app-release.apk: MISSING' }

Write-Output ''
Write-Output '=== 3. dist APK ==='
$dist = Join-Path $Repo 'dist\n7six.HamClock.v7.6.1.apk'
$di = Get-Item $dist
Write-Output ("dist APK: {0} bytes, {1}" -f $di.Length, $di.LastWriteTime)
Write-Output ("SHA256: {0}" -f (Get-FileHash $dist -Algorithm SHA256).Hash)

Write-Output ''
Write-Output '=== 4. staged native libs ==='
foreach ($abi in @('arm64-v8a','armeabi-v7a','x86_64','x86')) {
    $so = Join-Path $Repo "android\app\src\main\jniLibs\$abi\libhamclock.so"
    if (Test-Path $so) {
        $si = Get-Item $so
        $raw = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($so))
        $has761 = $raw.Contains('7.6.1')
        $has432 = $raw.Contains('4.32')
        Write-Output ("{0}: {1} bytes, {2}  has '7.6.1': {3}  has '4.32': {4}" -f $abi, $si.Length, $si.LastWriteTime, $has761, $has432)
    } else { Write-Output "${abi}: MISSING" }
}

Write-Output ''
Write-Output '=== 5. version strings inside dist APK (libhamclock.so) ==='
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($dist)
try {
    foreach ($e in $zip.Entries) {
        if ($e.FullName -like 'lib/*/libhamclock.so') {
            $ms = New-Object IO.MemoryStream
            $s = $e.Open()
            $s.CopyTo($ms)
            $s.Close()
            $raw = [Text.Encoding]::ASCII.GetString($ms.ToArray())
            Write-Output ("{0}: has '7.6.1' = {1}, has '4.32' = {2}" -f $e.FullName, $raw.Contains('7.6.1'), $raw.Contains('4.32'))
        }
    }
    # versionName via manifest is binary XML; try aapt if available
} finally { $zip.Dispose() }

Write-Output ''
Write-Output '=== 6. aapt versionName check ==='
$aapt = Get-ChildItem (Join-Path $Tools 'android-sdk\build-tools') -Recurse -Filter aapt.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($aapt) {
    Write-Output ("using: {0}" -f $aapt.FullName)
    & $aapt.FullName dump badging $dist | Select-String "package:|versionName|versionCode"
} else { Write-Output 'aapt.exe not found' }

Write-Output ''
Write-Output '=== 7. git status of build.gradle ==='
Push-Location $Repo
try {
    git status --porcelain -- android/app/build.gradle 2>&1
    git diff --stat -- android/app/build.gradle 2>&1
} finally { Pop-Location }
