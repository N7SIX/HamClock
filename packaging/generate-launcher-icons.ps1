# =============================================================================
# generate-launcher-icons.ps1  —  N7SIX HamClock  —  build launcher icon PNGs
# =============================================================================
# Resizes the master icon (android/Glossy HamClock Space Globe Icon.png) into
# per-density launcher icons under app/src/main/res/mipmap-*/ic_launcher.png:
#   mdpi 48 | hdpi 72 | xhdpi 96 | xxhdpi 144 | xxxhdpi 192
# Uses high-quality bicubic downscaling with alpha preserved.
# =============================================================================
[CmdletBinding()]
param(
    [string]$Source = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock\android\HamClock_Icon.png'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$Repo = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
$src  = $Source
$res  = Join-Path $Repo 'android\app\src\main\res'

# density folder -> edge length in px
$sizes = @{
    'mipmap-mdpi'    = 48
    'mipmap-hdpi'    = 72
    'mipmap-xhdpi'   = 96
    'mipmap-xxhdpi'  = 144
    'mipmap-xxxhdpi' = 192
}

$img = [System.Drawing.Image]::FromFile($src)
try {
    foreach ($d in $sizes.Keys) {
        $n   = $sizes[$d]
        $dir = Join-Path $res $d
        $null = New-Item -ItemType Directory -Path $dir -Force

        $bmp = New-Object System.Drawing.Bitmap($n, $n, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g.SmoothingMode      = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $g.PixelOffsetMode    = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $g.DrawImage($img, 0, 0, $n, $n)
        } finally {
            $g.Dispose()
        }

        $out = Join-Path $dir 'ic_launcher.png'
        $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        Write-Output ("{0}\ic_launcher.png  {1}x{2}  {3} bytes" -f $d, $n, $n, (Get-Item $out).Length)
    }
} finally {
    $img.Dispose()
}
Write-Output 'DONE'