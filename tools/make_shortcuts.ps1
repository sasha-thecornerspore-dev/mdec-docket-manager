# Creates Desktop and Start Menu shortcuts for MDEC Docket Manager.
# Called by Install.cmd; safe to run on its own.
#
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcuts.ps1
#   powershell -ExecutionPolicy Bypass -File tools\make_shortcuts.ps1 -Remove

param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'MDEC Docket Manager.pyw'
$icon     = Join-Path $root 'assets\mdec.ico'
$name     = 'MDEC Docket Manager.lnk'

$desktop   = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $name

if ($Remove) {
    foreach ($p in @($desktop, $startMenu)) {
        if (Test-Path $p) { Remove-Item $p -Force; Write-Host "removed $p" }
    }
    Write-Host ''
    Write-Host 'Shortcuts removed. Your cases, documents, and settings are untouched.'
    Write-Host 'They live in %APPDATA%\MDECDocketManager and your document folders.'
    exit 0
}

if (-not (Test-Path $launcher)) { throw "Launcher not found: $launcher" }

# pythonw.exe runs the launcher with no console window. Point the shortcut at it
# directly rather than at the .pyw, so the icon and taskbar grouping behave even
# if .pyw is associated with something else.
$pythonw = $null
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd) {
    $candidate = Join-Path (Split-Path -Parent $pyCmd.Source) 'pythonw.exe'
    if (Test-Path $candidate) { $pythonw = $candidate }
}
if (-not $pythonw) {
    $pwCmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($pwCmd) { $pythonw = $pwCmd.Source }
}
if (-not $pythonw) { throw 'pythonw.exe not found next to python.exe.' }

$shell = New-Object -ComObject WScript.Shell
foreach ($path in @($desktop, $startMenu)) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath       = $pythonw
    $lnk.Arguments        = '"' + $launcher + '"'
    $lnk.WorkingDirectory = $root
    $lnk.Description      = 'Monitor and manage a Maryland Judiciary case docket'
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Save()
    Write-Host "created $path"
}

Write-Host ''
Write-Host 'Shortcuts created. Look for "MDEC Docket Manager" on your Desktop.'
