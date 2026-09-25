param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,
    [Parameter(Mandatory = $true)]
    [string]$TimestampUrl
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $TimestampUrl.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The RFC 3161 timestamp URL must use HTTPS"
}
$certificateBase64 = $env:FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE
$certificatePassword = $env:FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD
if ([string]::IsNullOrWhiteSpace($certificateBase64)) {
    throw "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE is required"
}
if ([string]::IsNullOrWhiteSpace($certificatePassword)) {
    throw "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE_PASSWORD is required"
}

$signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($null -eq $signTool) {
    $candidates = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    $signTool = $candidates | Select-Object -First 1
}
if ($null -eq $signTool) { throw "signtool.exe was not found" }
$signToolPath = if ($signTool -is [System.Management.Automation.ApplicationInfo]) {
    $signTool.Source
} else {
    $signTool.FullName
}

$temporaryCertificate = Join-Path ([System.IO.Path]::GetTempPath()) ("financial-beancount-signing-" + [guid]::NewGuid() + ".pfx")
try {
    try {
        $certificateBytes = [Convert]::FromBase64String($certificateBase64)
    }
    catch {
        throw "FINANCIAL_BEANCOUNT_WINDOWS_CERTIFICATE must be a base64 PKCS#12 file"
    }
    [System.IO.File]::WriteAllBytes($temporaryCertificate, $certificateBytes)
    foreach ($item in $Path) {
        $resolved = (Resolve-Path -LiteralPath $item).Path
        & $signToolPath sign /f $temporaryCertificate /p $certificatePassword /fd SHA256 /tr $TimestampUrl /td SHA256 /d FinancialBeancount $resolved
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $resolved" }
        & $signToolPath verify /pa /tw /v $resolved
        if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed for $resolved" }
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryCertificate -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryCertificate -Force
    }
}
