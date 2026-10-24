# =============================================================================
# build-apk-native.ps1  —  cross-compile the native HamClock server for Android
# =============================================================================
# Windows-native equivalent of packaging/build-apk-native.sh. Compiles the SAME
# web-only C++ sources for one ABI using the NDK clang++ (invoked as .exe, so no
# WSL is needed), links a standalone ELF executable named `hamclock`, strips it,
# and stages it into android/app/src/main/jniLibs/<abi>/libhamclock.so so the package
# manager extracts it to the executable nativeLibraryDir at install time (Android 10+
# forbids exec() of files placed in the app's data home dir).
#
# Usage:
#   $env:ANDROID_NDK_HOME='C:\Users\sebue\hc-buildtools\android-sdk\ndk\26.3.11579264'
#   powershell -ExecutionPolicy Bypass -File packaging\build-apk-native.ps1 -Abi arm64-v8a
# =============================================================================
[CmdletBinding()]
param(
    [string]$Abi  = 'arm64-v8a',
    # NDK r26 floors at API 21 for 64-bit / 19 for 32-bit; request 17 but clamp
    # to the NDK floor. The Gradle minSdk stays 17 so one APK still installs on
    # 4.2.2 (old 32-bit tablets run the armeabi-v7a slice).
    [string]$Api  = '17',
    [string]$Res  = '1600x960',
    [string]$Repo = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
)
$ErrorActionPreference = 'Stop'

if (-not $env:ANDROID_NDK_HOME -or -not (Test-Path $env:ANDROID_NDK_HOME)) {
    throw "Set `$env:ANDROID_NDK_HOME to your Android NDK root (contains toolchains\)."
}
$NDK = $env:ANDROID_NDK_HOME
$BIN = Join-Path $NDK 'toolchains\llvm\prebuilt\windows-x86_64\bin'

switch ($Abi) {
    'arm64-v8a'   { $triple = 'aarch64-linux-android' }
    'armeabi-v7a' { $triple = 'armv7a-linux-androideabi' }
    'x86_64'      { $triple = 'x86_64-linux-android' }
    'x86'         { $triple = 'i686-linux-android' }
    default { throw "Unknown ABI: $Abi" }
}

$CLANG   = Join-Path $BIN 'clang++.exe'
$CLANG_C = Join-Path $BIN 'clang.exe'
$STRIP   = Join-Path $BIN 'llvm-strip.exe'
foreach ($t in @($CLANG,$CLANG_C,$STRIP)) { if (-not (Test-Path $t)) { throw "Missing NDK tool: $t" } }

# The ABI-specific *-clang++ files are bash/cmd wrappers; on Windows we call the
# base clang++.exe directly and pass the target + sysroot explicitly.
# NDK r26 floor: 64-bit needs 21+, 32-bit needs 19+ (armeabi-v7a/x86). Request
# 17 but clamp so an old requested API can never pick a missing sysroot.
$MinApi = @{ 'arm64-v8a' = 21; 'x86_64' = 21; 'armeabi-v7a' = 21; 'x86' = 21 }[$Abi]
if ([int]$Api -lt $MinApi) { $Api = "$MinApi" }
$TARGET  = "${triple}${Api}"
$SYSROOT = Join-Path $BIN '..\sysroot'
$COMMON  = @("--target=$TARGET", "--sysroot=$SYSROOT") -join ' '


$build = Join-Path $env:TEMP ("hamclock-$Abi-" + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $build -Force

$inc = @(
    "-I$Repo\include", "-I$Repo\src", "-I$Repo\ArduinoLib",
    "-I$Repo\wsServer\include", "-I$Repo\zlib-hc", "-I$Repo"
) -join ' '
$CXXFLAGS = @(
    '-std=c++17', '-O2', '-g', '-fPIC', '-pthread',
    '-D_WEB_ONLY', '-D__ANDROID__', "-D_CLOCK_$Res", $inc, '-Wno-unused-function'
) -join ' '

Write-Output ">> ABI=$Abi  triple=$triple  API=$Api  res=$Res"
Write-Output "   NDK=$NDK"

$objs = New-Object System.Collections.Generic.List[string]
function Compile-One([string]$src, [string]$cc) {
    $rel = $src.Substring($Repo.Length).TrimStart('\','/') -replace '[\\/]','_'
    $obj = Join-Path $build ($rel + '.o')
    & $cc ($COMMON + ' ' + $CXXFLAGS).Split(' ') -c $src -o $obj
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $src" }
    $objs.Add($obj)
}

foreach ($f in (Get-ChildItem "$Repo\ArduinoLib" -Filter *.cpp))     { Compile-One $f.FullName $CLANG }
foreach ($f in (Get-ChildItem "$Repo\wsServer\src" -Filter *.cpp))    { Compile-One $f.FullName $CLANG }
foreach ($f in (Get-ChildItem "$Repo\zlib-hc" -Filter *.cpp))         { Compile-One $f.FullName $CLANG }
foreach ($f in (Get-ChildItem "$Repo\src" -Filter *.cpp))             { Compile-One $f.FullName $CLANG }

# Standalone Android platform callbacks (android_request_exit/restart/open_url/
# get_clipboard) that the C++ code calls under _IS_ANDROID. Provided here since
# we run as a plain subprocess with no JNI/Activity host.
Compile-One "$Repo\termux\android-stubs.cpp" $CLANG

# fdsan workaround (C)
$fdsanObj = Join-Path $build 'disable-fdsan.o'
& $CLANG_C ($COMMON + ' -fPIC').Split(' ') -c "$Repo\termux\disable-fdsan.c" -o $fdsanObj
if ($LASTEXITCODE -ne 0) { throw 'fdsan compile failed' }
$objs.Add($fdsanObj)

$out = Join-Path $build 'hamclock.exe'
Write-Output ">> Linking ($($objs.Count) objects) -> $out"
& $CLANG ($COMMON + ' ' + $CXXFLAGS).Split(' ') -o $out $objs.ToArray() '-static-libstdc++' '-ldl' '-llog' '-lz' '-lm'
if ($LASTEXITCODE -ne 0) { throw 'Link failed' }
& $STRIP $out

$dest = Join-Path $Repo "android\app\src\main\jniLibs\$Abi"
$null = New-Item -ItemType Directory -Path $dest -Force
Copy-Item $out (Join-Path $dest 'libhamclock.so') -Force
Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue

$sz = [math]::Round((Get-Item (Join-Path $dest 'libhamclock.so')).Length/1MB,1)
Write-Output ">> Staged: $dest\libhamclock.so  ($sz MB)"
Write-Output ">> DONE ($Abi)"
