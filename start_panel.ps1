# Start neuroglancer-chat panel frontend only (for development)
# Usage: .\start_panel.ps1 [-NoStreaming]

param(
    [switch]$Streaming
)

Write-Host "Starting neuroglancer-chat panel frontend..." -ForegroundColor Cyan

# Set backend URL
$env:BACKEND = "http://127.0.0.1:8000"

# set no streaming mode
$env:USE_STREAMING = "false"

# Check for streaming mode flag
if ($Streaming) {
    $env:USE_STREAMING = "true"
    Write-Host "Streaming mode ENABLED - using streaming chat endpoint" -ForegroundColor Green
} else {
    $env:USE_STREAMING = "false"
    Write-Host "Streaming mode DISABLED - using standard chat endpoint" -ForegroundColor Yello
}

# Change to panel directory
Set-Location "$PSScriptRoot\src\neuroglancer_chat"

# Start panel in foreground
Write-Host ""
Write-Host "Starting panel frontend on http://127.0.0.1:8006..." -ForegroundColor Green
Write-Host "Open http://localhost:8006 in your browser" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

uv run python -m panel serve panel/panel_app.py --autoreload --port 8006 --address 127.0.0.1 --allow-websocket-origin=127.0.0.1:8006 --allow-websocket-origin=localhost:8006
