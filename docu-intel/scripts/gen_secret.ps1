1..3 | ForEach-Object {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes) -replace '\+', 'x' -replace '/', 'X'
    Write-Output $secret
}