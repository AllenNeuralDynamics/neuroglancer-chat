# Start neuroglancer-chat backend only (for development)
# Usage: .\start_backend.ps1 [-Timing]

param(
    [switch]$Timing
)

# Set backend URL for frontend
$env:BACKEND = "http://127.0.0.1:8000"

# set debug
$env:NEUROGLANCER_CHAT_DEBUG = "0"

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
Set-Location (Resolve-Path "$PSScriptRoot\..\src\neuroglancer_chat")

# If debug mode is enabled, set uvicorn log level to debug
# Set limit-max-requests to 500MB for large CSV uploads
if ($env:NEUROGLANCER_CHAT_DEBUG -eq "1") {
    Write-Host "Debug mode ENABLED - agent loop debug logging active" -ForegroundColor Magenta
    uv run python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --log-level debug --limit-max-requests 10000 --timeout-keep-alive 300
} else {
    uv run python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --limit-max-requests 10000 --timeout-keep-alive 300
}
Write-Host ""