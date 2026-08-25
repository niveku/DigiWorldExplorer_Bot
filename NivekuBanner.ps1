# The banner both entry points share. Dot-source it; it defines
# Show-NivekuBanner and prints nothing on its own.
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
