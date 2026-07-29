[CmdletBinding()]
param(
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
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
