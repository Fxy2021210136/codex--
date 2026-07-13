param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 4173,
  [string]$DataDir = ".\data",
  [switch]$Build
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\enable-utf8.ps1"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if ($Build) {
  node node_modules\typescript\bin\tsc -b --force
  node node_modules\vite\bin\vite.js build .
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$env:APP_HOST = $HostName
$env:PORT = "$Port"
$env:APP_DATA_DIR = $DataDir

Write-Host "Starting Schedule AI at http://${HostName}:${Port}/"
Write-Host "SQLite database: $((Resolve-Path -LiteralPath $DataDir).Path)\app.db"
python serve.py
