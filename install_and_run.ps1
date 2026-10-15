# =============================================================================
# LIFECORE-SWE: One-click setup and benchmark runner
# Competition model: gemma4:31b (gemma-4-31b-it-qat-w4a16-ct)
#
# Usage:
#   Right-click this file -> "Run with PowerShell"
#   OR from PowerShell:  .\install_and_run.ps1
#
# What this does:
#   1. Checks / installs Ollama
#   2. Pulls gemma4:31b (the competition model, ~20 GB)
#   3. Starts Ollama server in background
#   4. Installs Python dependencies
#   5. Clones Flask fixture and plants benchmark bugs
#   6. Runs the 5-condition benchmark
#   7. Saves results to experiments/results/real_repo/
# =============================================================================

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  LIFECORE-SWE Benchmark — Competition Model: gemma4:31b" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Check RAM
# ---------------------------------------------------------------------------
Write-Host "[1/7] Checking system RAM..." -ForegroundColor Yellow
$ram = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$ramGB = [math]::Round($ram / 1GB, 1)
Write-Host "  Total RAM: $ramGB GB"

$model = "gemma4:31b"
if ($ramGB -lt 20) {
    Write-Host "  WARNING: gemma4:31b needs ~20 GB RAM. You have $ramGB GB." -ForegroundColor Yellow
    if ($ramGB -ge 10) {
        $model = "gemma4:12b"
        Write-Host "  Switching to gemma4:12b (needs ~10 GB RAM)" -ForegroundColor Yellow
    } elseif ($ramGB -ge 6) {
        $model = "gemma4:4b"
        Write-Host "  Switching to gemma4:4b (needs ~6 GB RAM)" -ForegroundColor Yellow
    } else {
        $model = "gemma2:9b"
        Write-Host "  Switching to gemma2:9b (needs ~6 GB RAM)" -ForegroundColor Yellow
    }
}
Write-Host "  Selected model: $model" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 2: Install Ollama
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/7] Checking Ollama..." -ForegroundColor Yellow
$ollamaInstalled = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)

if (-not $ollamaInstalled) {
    Write-Host "  Ollama not found. Downloading installer..." -ForegroundColor Yellow
    $installerUrl = "https://ollama.com/download/OllamaSetup.exe"
    $installerPath = "$env:TEMP\OllamaSetup.exe"
    
    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "  Installing Ollama (silent install)..."
        Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait
        
        # Refresh PATH
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + 
                    [System.Environment]::GetEnvironmentVariable("PATH", "User")
        
        $ollamaInstalled = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)
        if ($ollamaInstalled) {
            Write-Host "  Ollama installed successfully." -ForegroundColor Green
        } else {
            Write-Host "  ERROR: Ollama install may need a restart." -ForegroundColor Red
            Write-Host "  Please restart PowerShell and re-run this script." -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "  ERROR downloading Ollama: $_" -ForegroundColor Red
        Write-Host "  Please install manually: https://ollama.com/download" -ForegroundColor Yellow
        exit 1
    }
} else {
    $version = ollama --version 2>&1
    Write-Host "  Ollama found: $version" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 3: Start Ollama server
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/7] Starting Ollama server..." -ForegroundColor Yellow

# Check if already running
$running = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) { $running = $true }
} catch {}

if (-not $running) {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Write-Host "  Waiting for server to start..."
    Start-Sleep -Seconds 5
    
    # Confirm it started
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 10
        Write-Host "  Ollama server running." -ForegroundColor Green
    } catch {
        Write-Host "  WARNING: Server may not have started. Continuing anyway..." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Ollama server already running." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 4: Pull the model
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/7] Pulling model: $model" -ForegroundColor Yellow

# Check if model already exists
$modelExists = $false
try {
    $tagsResp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 5
    $tags = ($tagsResp.Content | ConvertFrom-Json).models
    $modelExists = ($tags | Where-Object { $_.name -eq $model }) -ne $null
} catch {}

if ($modelExists) {
    Write-Host "  Model '$model' already available locally." -ForegroundColor Green
} else {
    Write-Host "  Downloading $model — this may take 10-30 minutes depending on connection..." -ForegroundColor Yellow
    Write-Host "  (gemma4:31b is ~20 GB; gemma4:12b is ~8 GB)" -ForegroundColor Gray
    ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to pull $model" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Model downloaded." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 5: Install Python dependencies
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/7] Installing Python dependencies..." -ForegroundColor Yellow
Set-Location $RepoRoot

& $PythonExe -m pip install -e . --quiet 2>&1 | Out-Null
Write-Host "  lifecore-swe installed." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 6: Setup Flask fixture
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/7] Setting up Flask benchmark fixture..." -ForegroundColor Yellow

$fixtureDir = Join-Path $RepoRoot "fixtures\real_repo_flask"
if (Test-Path $fixtureDir) {
    Write-Host "  Flask fixture already exists. Resetting to baseline..." -ForegroundColor Gray
    git -C $fixtureDir restore . 2>&1 | Out-Null
} else {
    Write-Host "  Cloning Flask v3.0.3 and planting benchmark bugs..."
    & $PythonExe (Join-Path $RepoRoot "scripts\setup_real_repo_benchmark.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Flask setup failed." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Flask fixture ready." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 7: Run benchmark
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[7/7] Running benchmark (all 5 conditions, 5 tasks)..." -ForegroundColor Yellow
Write-Host "  Model: $model"
Write-Host "  This will take 30-90 minutes. Progress shown below."
Write-Host ""

& $PythonExe (Join-Path $RepoRoot "scripts\run_benchmark_local.py") --model $model --runs 1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  Benchmark encountered errors. Check output above." -ForegroundColor Yellow
    Write-Host "  Partial results may have been saved." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  BENCHMARK COMPLETE" -ForegroundColor Green
    Write-Host "  Results: $RepoRoot\experiments\results\real_repo\" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
}

Write-Host ""
Write-Host "Next step: Update the paper with these results"
Write-Host "  python scripts/compute_statistical_analysis.py --source real_repo"
Write-Host ""
