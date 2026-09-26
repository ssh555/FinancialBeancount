param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath "FinancialBeancount.exe") -PathType Leaf)) {
    throw "The packaged application does not contain FinancialBeancount.exe"
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "MSI version must contain exactly three numeric fields"
}

$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
$intermediate = Join-Path ([System.IO.Path]::GetTempPath()) ("financial-beancount-wix-" + [guid]::NewGuid())
[System.IO.Directory]::CreateDirectory($intermediate) | Out-Null

try {
    $harvested = Join-Path $intermediate "ApplicationFiles.wxs"
    & heat.exe dir $sourcePath -nologo -ag -sfrag -srd -sreg -dr INSTALLFOLDER -cg ApplicationFiles -var var.SourceDir -out $harvested
    if ($LASTEXITCODE -ne 0) { throw "WiX heat failed with exit code $LASTEXITCODE" }

    $productObject = Join-Path $intermediate "Product.wixobj"
    $filesObject = Join-Path $intermediate "ApplicationFiles.wixobj"
    $productSource = Join-Path $PSScriptRoot "Product.wxs"
    & candle.exe -nologo -arch x64 "-dProductVersion=$Version" "-dSourceDir=$sourcePath" -out $productObject $productSource
    if ($LASTEXITCODE -ne 0) { throw "WiX candle failed for Product.wxs" }
    & candle.exe -nologo -arch x64 "-dSourceDir=$sourcePath" -out $filesObject $harvested
    if ($LASTEXITCODE -ne 0) { throw "WiX candle failed for harvested application files" }

    # These ICE rules assume machine-wide or roaming multi-user components. This package is
    # deliberately per-user under LocalAppData and supports same-version preview rebuilds. Keep all
    # other validation enabled; the install/upgrade/uninstall smoke test covers this exact lifecycle.
    $lightArguments = @(
        "-nologo",
        "-sice:ICE38",
        "-sice:ICE61",
        "-sice:ICE64",
        "-sice:ICE91",
        "-out",
        $outputPath,
        $productObject,
        $filesObject
    )
    if ($SkipValidation) {
        $lightArguments = @("-sval") + $lightArguments
    }
    & light.exe @lightArguments
    if ($LASTEXITCODE -ne 0) { throw "WiX light failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
        throw "WiX completed without producing the requested MSI"
    }
}
finally {
    if (Test-Path -LiteralPath $intermediate) {
        Remove-Item -LiteralPath $intermediate -Recurse -Force
    }
}

Write-Output $outputPath
