param(
  [string]$Output = ".\ScheduleAI.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "launcher\ScheduleAiLauncher.cs"
$outputPath = Join-Path $projectRoot $Output

if (!(Test-Path -LiteralPath $source)) {
  throw "Launcher source not found: $source"
}

Add-Type -Path $source -OutputAssembly $outputPath -OutputType WindowsApplication
Write-Host "Launcher built: $outputPath"
