# verify-icon2.apk — extract & inspect the packaged launcher icons
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.Drawing
$Repo = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
$apk  = Join-Path $Repo 'dist\n7six.HamClock.v7.6.1.apk'

# map from aapt badging: 160=mdpi, 240=hdpi, 320=xhdpi, 480=xxhdpi, 640=xxxhdpi
$map = @{ 160 = 'res/9w.png'; 240 = 'res/yn.png'; 320 = 'res/FS.png'; 480 = 'res/RJ.png'; 640 = 'res/o-.png' }
$expectPx = @{ 160 = 48; 240 = 72; 320 = 96; 480 = 144; 640 = 192 }

$zip = [IO.Compression.ZipFile]::OpenRead($apk)
$ext = Join-Path $env:TEMP 'hc-icon-check'
$null = New-Item -ItemType Directory -Path $ext -Force
try {
    foreach ($dpi in ($map.Keys | Sort-Object)) {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq $map[$dpi] } | Select-Object -First 1
        if (-not $entry) { Write-Output "$dpi dpi ($($map[$dpi])): MISSING"; continue }
        $dest = Join-Path $ext ("icon-$dpi.png")
        $s = $entry.Open(); $f = [IO.File]::Create($dest); $s.CopyTo($f); $f.Close(); $s.Close()
        $bmp = [System.Drawing.Image]::FromFile($dest)
        $ok = ($bmp.Width -eq $expectPx[$dpi] -and $bmp.Height -eq $expectPx[$dpi])
        Write-Output ("{0} dpi ({1}): {2}x{3} expected {4}  sizes-ok={5}  bytes={6}" -f `
            $dpi, $map[$dpi], $bmp.Width, $bmp.Height, $expectPx[$dpi], $ok, $entry.Length)
        $bmp.Dispose()
    }
    # keep the biggest one for visual check
    Copy-Item (Join-Path $ext 'icon-640.png') (Join-Path $Repo 'dist\icon-check-192.png') -Force
} finally { $zip.Dispose() }
Write-Output "extracted to $ext"