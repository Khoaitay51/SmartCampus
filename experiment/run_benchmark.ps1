<#
.SYNOPSIS
    Run the SmartCampus M0-M4 Docker benchmark from Windows PowerShell.

.EXAMPLE
    .\experiment\run_benchmark.ps1 -Provider gemini -Csv cases
    .\experiment\run_benchmark.ps1 -Provider gemini -Csv all_live
    .\experiment\run_benchmark.ps1 -Provider ollama -Model qwen2.5:7b -Csv e2e_cases
#>
[CmdletBinding()]
param(
    [ValidateSet("gemini", "ollama")]
    [string]$Provider = "gemini",

    [ValidateSet("cases", "e2e_cases", "all_live", "notification_guard")]
    [string]$Csv = "cases",

    [string]$Profile = "ALL",

    [string]$Model = "",

    [int]$AgentTimeout = 90,

    [int]$EvaluateTimeout = 70,

    [string]$OllamaUrl = "",

    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $PSScriptRoot "compose.test.yml"
$Project = "smartcampus-bench-$Provider"

function Read-DotEnvSetting {
    param([string]$EnvPath, [string]$Name)
    if (-not (Test-Path $EnvPath)) { return "" }
    foreach ($rawLine in Get-Content -Path $EnvPath -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        if ($line -match ('^(?:export\s+)?' + [regex]::Escape($Name) + '\s*=\s*(.+)$')) {
            $val = $matches[1].Trim()
            if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
                return $val.Substring(1, $val.Length - 2)
            }
            $hashIdx = $val.IndexOf(" #")
            if ($hashIdx -ge 0) { $val = $val.Substring(0, $hashIdx).Trim() }
            return $val
        }
    }
    return ""
}

function Ensure-BenchPython {
    $VenvDir = Join-Path $RepoRoot ".venv_bench"
    $WinPy = Join-Path (Join-Path $VenvDir "Scripts") "python.exe"
    $UnixPy = Join-Path (Join-Path $VenvDir "bin") "python"
    if (Test-Path $WinPy) { return $WinPy }
    if (Test-Path $UnixPy) { return $UnixPy }

    Write-Host ">>> Creating benchmark virtualenv in $VenvDir ..."
    $Created = $false
    foreach ($Candidate in @("python", "py")) {
        $Cmd = Get-Command $Candidate -ErrorAction SilentlyContinue
        if (-not $Cmd) { continue }
        $ExtraArgs = if ($Candidate -eq "py") { @("-3") } else { @() }
        & $Cmd.Source @ExtraArgs -c "import venv" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $Cmd.Source @ExtraArgs -m venv $VenvDir
            if ($LASTEXITCODE -eq 0) {
                $Created = $true
                break
            }
        }
    }
    if (-not $Created) { throw "Failed to create .venv_bench (Python 3.11+ with venv module required)." }

    $VenvPip = Join-Path (Join-Path $VenvDir "Scripts") "pip.exe"
    if (-not (Test-Path $VenvPip)) {
        $VenvPip = Join-Path (Join-Path $VenvDir "bin") "pip"
    }
    $ReqFile = Join-Path (Join-Path $RepoRoot "benchmark") "requirements.txt"
    & $VenvPip install -r $ReqFile
    if ($LASTEXITCODE -ne 0) { throw "Failed to install benchmark/requirements.txt." }

    if (Test-Path $WinPy) { return $WinPy }
    return $UnixPy
}

$PyExe = Ensure-BenchPython

# Resolve manifest path
$BenchmarkLocalDir = Join-Path $RepoRoot "benchmark_local"
$ManifestPath = switch ($Csv) {
    "cases"              { Join-Path $PSScriptRoot "cases.csv" }
    "e2e_cases"          { Join-Path $PSScriptRoot "e2e_cases.csv" }
    "notification_guard" { Join-Path $PSScriptRoot "notification_guard_cases.csv" }
    "all_live" {
        $LocalAll = Join-Path $BenchmarkLocalDir "all_cases_live.csv"
        if (Test-Path $LocalAll) {
            $LocalAll
        }
        else {
            New-Item -ItemType Directory -Force -Path $BenchmarkLocalDir | Out-Null
            $GenAll = Join-Path $BenchmarkLocalDir "generated_all_cases_live.csv"
            $SrcE2E = Join-Path $PSScriptRoot "e2e_cases.csv"
            $PyScript = @'
import csv, sys
with open(sys.argv[1], encoding="utf-8-sig", newline="") as f1:
    rows = list(csv.DictReader(f1))
with open(sys.argv[2], "w", encoding="utf-8", newline="") as f2:
    writer = csv.DictWriter(f2, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        if row["scope"] in ("local_policy", "local_contract") and row["implementation"] == "not_e2e":
            row["implementation"] = "implemented"
        writer.writerow(row)
'@
            $PyScript | & $PyExe - $SrcE2E $GenAll
            if ($LASTEXITCODE -ne 0) { throw "Failed to generate all_live manifest." }
            $GenAll
        }
    }
}

if (-not $Output) {
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $RunsDir = Join-Path $BenchmarkLocalDir "runs"
    New-Item -ItemType Directory -Force -Path $RunsDir | Out-Null
    $Output = Join-Path $RunsDir "$Csv-$Provider-$Stamp"
}

# Configure provider environment
$DotEnvPath = Join-Path (Join-Path $RepoRoot "AI + Backend") ".env"
$env:BENCH_LLM_PROVIDER = $Provider
$env:BENCH_EVALUATE_TIMEOUT_SECONDS = "$EvaluateTimeout"
$env:BENCH_EDGE_DSN = "postgresql://bench:local_fixture_only@127.0.0.1:25434/edgebench"
$env:BENCH_BACKEND_DSN = "postgresql://bench:local_fixture_only@127.0.0.1:25433/backendbench"

if ($Provider -eq "gemini") {
    $ApiKey = Read-DotEnvSetting -EnvPath $DotEnvPath -Name "GEMINI_API_KEY"
    if (-not $ApiKey) { $ApiKey = $env:GEMINI_API_KEY }
    if (-not $ApiKey) { throw "Missing GEMINI_API_KEY in 'AI + Backend\.env' or environment." }
    $env:GEMINI_API_KEY = $ApiKey

    $GeminiModel = $Model
    if (-not $GeminiModel) { $GeminiModel = Read-DotEnvSetting -EnvPath $DotEnvPath -Name "AGENT" }
    if (-not $GeminiModel) { $GeminiModel = $env:BENCH_GEMINI_MODEL }
    if (-not $GeminiModel) { $GeminiModel = "gemini-3.8-flash" }
    $env:BENCH_GEMINI_MODEL = $GeminiModel
    $env:BENCH_OLLAMA_FALLBACK_MODEL = ""
    Write-Host ">>> Provider: gemini ($GeminiModel) | Manifest: $ManifestPath"
}
else {
    $OllamaModel = $Model
    if (-not $OllamaModel) { $OllamaModel = $env:BENCH_OLLAMA_MODEL }
    if (-not $OllamaModel) { $OllamaModel = "qwen2.5:7b" }
    $env:BENCH_OLLAMA_MODEL = $OllamaModel
    if ($OllamaUrl) { $env:BENCH_OLLAMA_URL = $OllamaUrl }
    Write-Host ">>> Provider: ollama ($OllamaModel) | Manifest: $ManifestPath"
}

$ProfileArgs = @()
if ($Profile.ToUpper() -ne "ALL") {
    foreach ($p in ($Profile -split ",")) {
        $trimmed = $p.Trim().ToUpper()
        if ($trimmed) {
            $ProfileArgs += "--profile"
            $ProfileArgs += $trimmed
        }
    }
}

$BenchExit = 1
Push-Location $RepoRoot
try {
    docker compose -p $Project -f $ComposeFile up -d --pull never api ai-agent
    if ($LASTEXITCODE -ne 0) { throw "Failed to start benchmark containers." }

    $Ready = $false
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $Status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:28001/api/recommendations/hitl/status" -TimeoutSec 3
            if ($null -ne $Status) {
                $Ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $Ready) { throw "Backend test container did not become ready on port 28001." }

    try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:28001/api/auth/rootadmin" -TimeoutSec 5 | Out-Null } catch {}
    $Login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:28001/api/auth/login/json" -ContentType "application/json" -Body '{"email":"admin","password":"admin123456"}' -TimeoutSec 5
    $env:BENCH_APPROVAL_TOKEN = $Login.access_token

    $BenchArgs = @(
        (Join-Path $PSScriptRoot "run_benchmark.py"),
        "--isolated-test-stack",
        "--manage-compose",
        "--project", $Project,
        "--compose-file", $ComposeFile,
        "--manifest", $ManifestPath,
        "--model-source", "live",
        "--edge-url", "http://127.0.0.1:28000",
        "--backend-url", "http://127.0.0.1:28001",
        "--mqtt-port", "21883",
        "--mqtt-window", "4",
        "--agent-timeout", "$AgentTimeout",
        "--output", $Output
    ) + $ProfileArgs

    & $PyExe @BenchArgs
    $BenchExit = $LASTEXITCODE
}
finally {
    Write-Host ">>> Stopping benchmark containers ($Project)..."
    docker compose -p $Project -f $ComposeFile down
    Pop-Location
}

Write-Host ">>> Benchmark finished (exit=$BenchExit). Output: $Output"
exit $BenchExit
