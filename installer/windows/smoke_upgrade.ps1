param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$CurrentMsi,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$currentMsiPath = (Resolve-Path -LiteralPath $CurrentMsi).Path
$workingDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("financial-beancount-msi-smoke-" + [guid]::NewGuid())
[System.IO.Directory]::CreateDirectory($workingDirectory) | Out-Null
$previousMsi = Join-Path $workingDirectory "FinancialBeancount-previous.msi"
$installedExecutable = Join-Path $env:LOCALAPPDATA "Programs\FinancialBeancount\FinancialBeancount.exe"
$dataDirectory = Join-Path $env:LOCALAPPDATA "FinancialBeancount"
$sentinel = Join-Path $dataDirectory "installer-upgrade-sentinel.txt"
$previousInstalled = $false
$currentInstalled = $false

function Invoke-Msi {
    param([string[]]$Arguments)
    & msiexec.exe @Arguments
    if ($LASTEXITCODE -notin @(0, 1641, 3010)) {
        throw "msiexec failed with exit code $LASTEXITCODE"
    }
}

function Remove-TemporaryDirectory {
    param([string]$Path)
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Wait-PathState {
    param(
        [string]$Path,
        [bool]$Exists
    )
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        if ((Test-Path -LiteralPath $Path -PathType Leaf) -eq $Exists) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for path state Exists=$Exists`: $Path"
}

try {
    $buildArguments = @{
        Source = $sourcePath
        Output = $previousMsi
        Version = "0.0.1"
        SkipValidation = $SkipValidation
    }
    & (Join-Path $PSScriptRoot "build.ps1") @buildArguments
    Invoke-Msi -Arguments @("/i", $previousMsi, "/qn", "/norestart")
    $previousInstalled = $true
    Wait-PathState -Path $installedExecutable -Exists $true
    if (-not (Test-Path -LiteralPath $installedExecutable -PathType Leaf)) {
        throw "previous MSI did not install the application executable"
    }

    [System.IO.Directory]::CreateDirectory($dataDirectory) | Out-Null
    [System.IO.File]::WriteAllText($sentinel, "preserve-user-ledger")
    Invoke-Msi -Arguments @("/i", $currentMsiPath, "/qn", "/norestart")
    $previousInstalled = $false
    $currentInstalled = $true
    Wait-PathState -Path $installedExecutable -Exists $true
    if (-not (Test-Path -LiteralPath $installedExecutable -PathType Leaf)) {
        throw "major upgrade removed the application executable"
    }
    if ((Get-Content -LiteralPath $sentinel -Raw) -ne "preserve-user-ledger") {
        throw "major upgrade modified per-user ledger data"
    }

    Invoke-Msi -Arguments @("/x", $currentMsiPath, "/qn", "/norestart")
    $currentInstalled = $false
    Wait-PathState -Path $installedExecutable -Exists $false
    if (Test-Path -LiteralPath $installedExecutable -PathType Leaf) {
        throw "MSI uninstall left the application executable installed"
    }
    if ((Get-Content -LiteralPath $sentinel -Raw) -ne "preserve-user-ledger") {
        throw "MSI uninstall removed or modified per-user ledger data"
    }
}
finally {
    if ($currentInstalled) {
        & msiexec.exe /x $currentMsiPath /qn /norestart
    }
    if ($previousInstalled) {
        & msiexec.exe /x $previousMsi /qn /norestart
    }
    if (Test-Path -LiteralPath $sentinel -PathType Leaf) {
        Remove-Item -LiteralPath $sentinel -Force
    }
    if (Test-Path -LiteralPath $workingDirectory) {
        Remove-TemporaryDirectory -Path $workingDirectory
    }
}

Write-Output "Windows MSI install, major upgrade, uninstall and data-preservation smoke passed."
