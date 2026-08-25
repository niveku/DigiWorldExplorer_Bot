[CmdletBinding()]
param(
    [string]$Loop = '',
    [int]$Cycles = 0,
    # Adopt a run that is already on screen when the loop starts. Needed
    # only after a launch that was killed on a reward panel; see the
    # prompt below and `adopt_session` in screen_loop.py.
    [switch]$AdoptSession,
    [switch]$Active,
    [string]$Adb = 'auto',
    [string]$Serial = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$loopScript = Join-Path $projectRoot 'screen_loops.py'
$profilesDir = Join-Path $projectRoot 'screen_profiles'

. (Join-Path $PSScriptRoot 'NivekuBanner.ps1')
Show-NivekuBanner
Write-Host '  Loops de pantalla repetible (dungeon, defensa, invocacion)' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Falta el entorno local de Python. Ejecuta primero INSTALL.cmd.'
}

# Which loops exist is a question about the disk, not about memory: the
# profiles are what the runner can actually recognize, so they are the menu.
function Select-Loop {
    param([string]$Preset)
    $available = @(Get-ChildItem -LiteralPath $profilesDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName })
    if (-not $available) {
        throw "No hay perfiles en $profilesDir. Enseña uno primero (ver SCREEN_LOOPS.md)."
    }
    if ($Preset) {
        if ($available -notcontains $Preset) {
            throw "No existe el perfil '$Preset'. Hay: $($available -join ', ')."
        }
        return $Preset
    }
    if ($available.Count -eq 1) { return $available[0] }
    Write-Host 'Loops disponibles:'
    for ($i = 0; $i -lt $available.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f ($i + 1), $available[$i])
    }
    while ($true) {
        $answer = Read-Host "¿Cuál? [1-$($available.Count)]"
        $parsed = 0
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le $available.Count) {
            return $available[$parsed - 1]
        }
    }
}

function Read-Cycles {
    $parsed = 0
    while ($true) {
        $answer = Read-Host '¿Cuántas vueltas? [Enter = sin límite]'
        if ([string]::IsNullOrWhiteSpace($answer)) { return 0 }
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -gt 0) { return $parsed }
        Write-Host '  Un entero positivo, o Enter para dejarlo abierto.' -ForegroundColor Yellow
    }
}

$loopName = Select-Loop -Preset $Loop
$runCycles = $Cycles
$adopt = [bool]$AdoptSession
$dryRun = -not $Active

do {
    if (-not $Active) {
        Write-Host ''
        Write-Host 'SIMULACION primero: reconoce las pantallas y dice qué haría, sin tocar nada.' -ForegroundColor Cyan
        Write-Host 'Es la forma soportada de descubrir que un perfil lee mal ANTES de gastar entradas.' -ForegroundColor DarkGray
    }
    if ($runCycles -le 0 -and -not $dryRun) { $runCycles = Read-Cycles }

    $arguments = @(
        $loopScript, '--adb', $Adb, '--serial', $Serial,
        $(if ($dryRun) { 'watch' } else { 'run' }),
        '--loop', $loopName
    )
    if ($runCycles -gt 0 -and -not $dryRun) { $arguments += @('--cycles', $runCycles) }
    if ($adopt -and -not $dryRun) { $arguments += '--adopt-session' }
    if ($dryRun) { $arguments += @('--max-frames', '15') }

    Write-Host ''
    if ($dryRun) {
        Write-Host "● SIMULANDO '$loopName' (15 frames) ..." -ForegroundColor Cyan
    } else {
        $budget = if ($runCycles -gt 0) { "$runCycles vueltas" } else { 'sin límite' }
        Write-Host "● LOOP '$loopName' EN MARCHA ...  ($budget)" -ForegroundColor Green
        Write-Host '  Ctrl+C para parar.' -ForegroundColor DarkGray
    }
    Set-Location -LiteralPath $projectRoot
    & $python @arguments
    $lastStatus = $LASTEXITCODE

    if ($dryRun) {
        Write-Host ''
        Write-Host 'Si cada pantalla salió con el nombre correcto, puedes arrancar de verdad.' -ForegroundColor DarkGray
        $answer = Read-Host '¿Arrancar el loop ACTIVO? [s/N]'
        if ($answer -notmatch '^(s|si|sí|y|yes)$') {
            Write-Host 'Cancelado.' -ForegroundColor Yellow
            break
        }
        # A leftover reward panel is the one thing that deadlocks a fresh
        # launch, and it is not rare: any run killed mid-cycle leaves one.
        # Asking here beats watching "sin sesion propia" scroll forever.
        Write-Host ''
        Write-Host '¿El juego está AHORA en una pantalla de recompensa/derrota de una vuelta anterior?' -ForegroundColor DarkGray
        Write-Host 'Si respondes sí, el loop cerrará esa pantalla UNA vez; después vuelve a no tocar' -ForegroundColor DarkGray
        Write-Host 'nada que no haya abierto él mismo.' -ForegroundColor DarkGray
        $leftover = Read-Host '¿Adoptar esa vuelta? [s/N]'
        if ($leftover -match '^(s|si|sí|y|yes)$') { $adopt = $true }
        $dryRun = $false
        $again = $true
        continue
    }

    if ($lastStatus -eq 0) {
        Write-Host 'Loop finalizado.' -ForegroundColor Green
    } elseif ($lastStatus -eq 130) {
        Write-Host 'Interrumpido.' -ForegroundColor Yellow
    } else {
        Write-Host "Loop finalizado con exit code $lastStatus." -ForegroundColor Yellow
    }
    Write-Host ''
    $againAnswer = Read-Host '¿Otra tanda? [s/N]'
    $again = $againAnswer -match '^(s|si|sí|y|yes)$'
    if ($again) { $runCycles = 0; $adopt = $false }
} while ($again)

exit $lastStatus
