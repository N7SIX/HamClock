# brace-check.ps1 — verify MainActivity.kt brace balance and key markers
$path = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock\android\app\src\main\kotlin\my\hamradio\n7six\hamclock\MainActivity.kt'
$text = [IO.File]::ReadAllText($path)
$open  = ([regex]::Matches($text, [regex]::Escape('{'))).Count
$close = ([regex]::Matches($text, [regex]::Escape('}'))).Count
Write-Output "open={$open} close={$close} balanced=$($open -eq $close)"
$lines = Get-Content $path
$depth = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    $depth += ([regex]::Matches($lines[$i], [regex]::Escape('{'))).Count
    $depth -= ([regex]::Matches($lines[$i], [regex]::Escape('}'))).Count
    if ($lines[$i] -match '^\s*(private fun|override fun|class )') {
        Write-Output (('{0,4} depth={1}  {2}' -f ($i + 1), $depth, $lines[$i].Trim()))
    }
}
Write-Output "final depth=$depth"