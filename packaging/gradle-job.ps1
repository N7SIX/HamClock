<#
  Gradle build job - runs in background.
  Writes log to packaging/gradle-build-job.log
#>
$ErrorActionPreference = 'Continue'

$repo = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock'
$androidDir = Join-Path $repo 'android'
$logFile = Join-Path $repo 'packaging/gradle-build-job.log'
$resultFile = Join-Path $repo 'packaging/build-job-result.txt'

Write-Output "Starting Gradle build job..."
Push-Location $androidDir
try {
    & 'c:/Users/sebue/Documents/N7SIX/Software/HamClock/android/gradlew.bat' assembleDebug --no-daemon --warning-mode summary 2>&1 | Out-File -FilePath $logFile -Encoding UTF8
    $exit = $LASTEXITCODE
    Write-Output "Build finished with exit code: $exit" | Out-File -FilePath $resultFile -Encoding UTF8
} finally {
    Pop-Location
}
