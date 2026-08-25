[CmdletBinding()]
param(
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
function Show-NivekuBanner {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch {}

    $logo = @(
        '███╗   ██╗ ██╗ ██╗   ██╗ ███████╗ ██╗  ██╗ ██╗   ██╗'
        '████╗  ██║ ██║ ██║   ██║ ██╔════╝ ██║ ██╔╝ ██║   ██║'
        '██╔██╗ ██║ ██║ ██║   ██║ █████╗   █████╔╝  ██║   ██║'
        '██║╚██╗██║ ██║ ╚██╗ ██╔╝ ██╔══╝   ██╔═██╗  ██║   ██║'
        '██║ ╚████║ ██║  ╚████╔╝  ███████╗ ██║  ██╗ ╚██████╔╝'
        '╚═╝  ╚═══╝ ╚═╝   ╚═══╝   ╚══════╝ ╚═╝  ╚═╝  ╚═════╝ '
    )
    $versionPath = Join-Path $PSScriptRoot 'VERSION'
    $version = if (Test-Path -LiteralPath $versionPath) { (Get-Content -LiteralPath $versionPath -Raw).Trim() } else { 'dev' }
    $subtitle = "[ Digimon UP - DigiWorldExplorer_Bot v$version ]"
    $guildLine = '✨ Fork de Niveku · base de RobinTh0r ✨'
    # The box is as wide as its widest LINE, not as its widest logo
    # row: a subtitle or credit line longer than the art used to run
    # straight through the right border.
    $contentWidth = (@($logo) + @($subtitle, $guildLine) |
        ForEach-Object Length | Measure-Object -Maximum).Maximum

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
Show-NivekuBanner
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Falta el entorno local de Python. Ejecuta primero INSTALL.cmd.'
}

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$output = Join-Path $projectRoot "runs\checks\$stamp"
New-Item -ItemType Directory -Force -Path $output | Out-Null
Set-Location -LiteralPath $projectRoot

Write-Host 'Verificando ADB y detección del tablero - no se envía ningún clic.' -ForegroundColor Cyan
& $python (Join-Path $projectRoot 'digiworld_bot.py') --adb $Adb --serial $Serial --out $output
$status = $LASTEXITCODE
if ($status -eq 0) {
    Write-Host "Verificación completada. Diagnóstico: $output" -ForegroundColor Green
} else {
    Write-Host "Verificación fallida (exit code $status). Ver README > Solución de problemas." -ForegroundColor Yellow
}
exit $status
