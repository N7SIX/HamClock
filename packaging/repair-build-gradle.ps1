# =============================================================================
# repair-build-gradle.ps1  —  N7SIX HamClock  —  restore android/app/build.gradle
# =============================================================================
# The file was corrupted (UTF-8 BOM + all newlines stripped + wrong SDK values).
# Rewrites it cleanly: no BOM, CRLF newlines, last-known-good SDK config from
# the successful 2:45 PM build (compileSdk 34 / minSdk 24 / targetSdk 34).
# =============================================================================
$ErrorActionPreference = 'Stop'
$path = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock\android\app\build.gradle'

$lines = @(
"apply plugin: 'com.android.application'"
"apply plugin: 'org.jetbrains.kotlin.android'"
""
"android {"
"    namespace 'my.hamradio.n7six.hamclock'"
"    compileSdk 34"
""
"    defaultConfig {"
"        applicationId `"my.hamradio.n7six.hamclock`""
"        minSdk 24"
"        targetSdk 34"
"        versionCode 761"
"        versionName `"7.6.1`""
"    }"
""
"    buildTypes {"
"        release {"
"            minifyEnabled false"
"            shrinkResources false"
"            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'"
"            // Debug-signed so the APK is immediately installable."
"            // Re-sign with your own key before publishing to an app store."
"            signingConfig signingConfigs.debug"
"        }"
"    }"
""
"    compileOptions {"
"        sourceCompatibility JavaVersion.VERSION_17"
"        targetCompatibility JavaVersion.VERSION_17"
"    }"
"    kotlinOptions {"
"        jvmTarget = '17'"
"    }"
""
"    // The native HamClock server binary ships as a native library"
"    // (libhamclock.so per-ABI under src/main/jniLibs, built by"
"    // packaging/build-apk-native.ps1). Android 10+ forbids execve() of files"
"    // in the app's data home dir, but the package manager extracts jniLibs to"
"    // the executable nativeLibraryDir at install time, so we exec it from there."
"    packagingOptions {"
"        jniLibs.useLegacyPackaging true"
"    }"
"}"
""
"dependencies {"
"    implementation 'androidx.appcompat:appcompat:1.6.1'"
"}"
)

$content = ($lines -join "`r`n") + "`r`n"
[IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($false)))

# Verify byte-level: no BOM, has newlines
$bytes = [IO.File]::ReadAllBytes($path)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$nl = ([regex]::Matches([Text.Encoding]::UTF8.GetString($bytes), "`n")).Count
Write-Output "Wrote $path"
Write-Output ("Bytes: {0}  BOM: {1}  Newlines: {2}" -f $bytes.Length, $hasBom, $nl)
if ($hasBom) { throw 'BOM still present!' }
if ($nl -lt 10) { throw 'Newlines missing - file not properly written' }
Write-Output 'OK'
