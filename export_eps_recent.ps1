param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$mysqlClient = 'D:\Apps\MySQL\MySQL Server 8.4\bin\mysql.exe'
$sqlPath = Join-Path $projectRoot 'sql\export_live_epsstat_recent.sql'
$targetPath = Join-Path $projectRoot 'data\epsstat_live_raw_2026.tsv'
$temporaryPath = Join-Path $projectRoot ('data\epsstat_live_raw_2026.' + [guid]::NewGuid().ToString('N') + '.tmp')

if (-not (Test-Path -LiteralPath $mysqlClient)) {
    throw "MySQL client not found: $mysqlClient"
}
$mysqlUser = Read-Host 'MySQL username'
if ([string]::IsNullOrWhiteSpace($mysqlUser)) {
    throw 'A MySQL username is required.'
}
$query = Get-Content -LiteralPath $sqlPath -Raw -Encoding UTF8
Write-Host 'MySQL will ask for the password in this terminal. It will not be saved.'

try {
    & $mysqlClient --host=127.0.0.1 --port=3306 --user=$mysqlUser --password `
        --default-character-set=utf8mb4 --batch --raw --quick `
        --skip-column-names --database=gangtise --execute=$query |
        Set-Content -LiteralPath $temporaryPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL export failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $temporaryPath) -or
        (Get-Item -LiteralPath $temporaryPath).Length -eq 0) {
        throw 'MySQL returned an empty export.'
    }
    Move-Item -LiteralPath $temporaryPath -Destination $targetPath -Force
    Write-Host "Export saved: $targetPath"
} finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath
    }
}
