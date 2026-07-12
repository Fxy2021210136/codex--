param(
  [int]$Bytes = 32
)

if ($Bytes -lt 24) {
  throw "Bytes must be at least 24 for a strong ADMIN_TOKEN."
}

$buffer = New-Object byte[] $Bytes
try {
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($buffer)
}
finally {
  if ($rng) {
    $rng.Dispose()
  }
}
$token = [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
Write-Output $token
