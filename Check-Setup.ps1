[CmdletBinding()]
param(
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
function Show-RobinThorBanner {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

    $logo = @(
        '██████╗  ██████╗ ██████╗ ██╗███╗   ██╗████████╗██╗  ██╗ ██████╗ ██████╗ '
        '██╔══██╗██╔═══██╗██╔══██╗██║████╗  ██║╚══██╔══╝██║  ██║██╔═══██╗██╔══██╗'
        '██████╔╝██║   ██║██████╔╝██║██╔██╗ ██║   ██║   ███████║██║   ██║██████╔╝'
        '██╔══██╗██║   ██║██╔══██╗██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══██╗'
        '██║  ██║╚██████╔╝██████╔╝██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝██║  ██║'
        '╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝'
    )
    $versionPath = Join-Path $PSScriptRoot 'VERSION'
    $version = if (Test-Path -LiteralPath $versionPath) { (Get-Content -LiteralPath $versionPath -Raw).Trim() } else { 'dev' }
    $subtitle = "[ Digimon UP - DigiWorldExplorer_Bot v$version ]"
    $guildLine = '✨ EXCLUSIVE FOR GERMON MEMBERS ✨'
    $contentWidth = ($logo | ForEach-Object Length | Measure-Object -Maximum).Maximum

    function Center-BannerText([string]$Text) {
        $left = [Math]::Max(0, [Math]::Floor(($contentWidth - $Text.Length) / 2))
        return ((' ' * $left) + $Text).PadRight($contentWidth)
    }

    Write-Host ''
    Write-Host ('╔' + ('═' * ($contentWidth + 2)) + '╗') -ForegroundColor Yellow
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    foreach ($line in $logo) {
        Write-Host ('║ ' + $line.PadRight($contentWidth) + ' ║') -ForegroundColor Yellow
    }
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    Write-Host ('║ ' + (Center-BannerText $subtitle) + ' ║') -ForegroundColor Cyan
    Write-Host ('║ ' + (Center-BannerText $guildLine) + ' ║') -ForegroundColor Yellow
    Write-Host ('║ ' + (' ' * $contentWidth) + ' ║') -ForegroundColor Yellow
    Write-Host ('╚' + ('═' * ($contentWidth + 2)) + '╝') -ForegroundColor Yellow
    Write-Host ''
}
Show-RobinThorBanner
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Die lokale Python-Umgebung fehlt. Zuerst INSTALL.cmd ausfuehren.'
}

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$output = Join-Path $projectRoot "runs\checks\$stamp"
New-Item -ItemType Directory -Force -Path $output | Out-Null
Set-Location -LiteralPath $projectRoot

Write-Host 'Pruefe ADB und Spielfelderkennung - es werden keine Klicks gesendet.' -ForegroundColor Cyan
& $python (Join-Path $projectRoot 'digiworld_bot.py') --adb $Adb --serial $Serial --out $output
$status = $LASTEXITCODE
if ($status -eq 0) {
    Write-Host "Pruefung abgeschlossen. Diagnose: $output" -ForegroundColor Green
} else {
    Write-Host "Pruefung fehlgeschlagen (Exit-Code $status). Siehe README > Fehlerbehebung." -ForegroundColor Yellow
}
exit $status
