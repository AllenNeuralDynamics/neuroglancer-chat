# Start neurogabber backend only (for development)
# Usage: .\start_backend.ps1 [-Timing]

param(
    [switch]$Timing
)

# Set backend URL for frontend
$env:BACKEND = "http://127.0.0.1:8000"

# set debug
$env:NEUROGABBER_DEBUG = "1"


# Start backend in foreground
Write-Host "Starting backend on http://127.0.0.1:8000..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# Check for timing mode flag
if ($Timing) {
    $env:TIMING_MODE = "true"
    Write-Host "Timing mode ENABLED - performance metrics will be logged to ./logs/agent_timing.jsonl" -ForegroundColor Yellow
} else {
    $env:TIMING_MODE = "false"
}

# Change to backend directory
Set-Location "$PSScriptRoot\src\neurogabber"

# If debug mode is enabled, set uvicorn log level to debug
if ($env:NEUROGABBER_DEBUG -eq "1") {
    Write-Host "Debug mode ENABLED - agent loop debug logging active" -ForegroundColor Magenta
    uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --log-level debug
} else {
    uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
}
Write-Host ""