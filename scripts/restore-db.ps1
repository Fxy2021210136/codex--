param(
  [Parameter(Mandatory=$true)]
  [string]$BackupFile,
  [string]$Database = ".\data\app.db",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $BackupFile)) {
  Write-Error "Backup file not found: $BackupFile"
}

if ((Test-Path -LiteralPath $Database) -and -not $Force) {
  Write-Error "Target database already exists. Stop serve.py first, then rerun with -Force."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Database) | Out-Null
Copy-Item -LiteralPath $BackupFile -Destination $Database -Force

foreach ($suffix in @("-wal", "-shm")) {
  $sidecar = "$BackupFile$suffix"
  $targetSidecar = "$Database$suffix"
  if (Test-Path -LiteralPath $sidecar) {
    Copy-Item -LiteralPath $sidecar -Destination $targetSidecar -Force
  } elseif (Test-Path -LiteralPath $targetSidecar) {
    Remove-Item -LiteralPath $targetSidecar -Force
  }
}

Write-Host "Database restored to: $Database"
