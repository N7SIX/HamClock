# extract-gradle-errors.ps1 — print Kotlin/Gradle error lines from the build log
$log = 'C:\Users\sebue\hc-buildtools\dist\final-build.log'
$lines = Get-Content $log
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'error:|^e: |FAILED|What went wrong|Execution failed') {
        $start = [Math]::Max(0, $i - 2)
        $end   = [Math]::Min($lines.Count - 1, $i + 4)
        Write-Output ('--- context lines {0}-{1} ---' -f ($start + 1), ($end + 1))
        for ($j = $start; $j -le $end; $j++) { Write-Output $lines[$j] }
        Write-Output ''
    }
}
