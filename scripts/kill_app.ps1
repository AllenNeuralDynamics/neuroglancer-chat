# Kill all Neuroglancer-Chat-related processes
# This script stops the backend (uvicorn) and frontend (panel serve) processes

Write-Host "Stopping Neuroglancer-Chat processes..." -ForegroundColor Yellow

# Kill uvicorn processes (backend)
$uvicornProcesses = Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue
if ($uvicornProcesses)
{
    Write-Host "Stopping uvicorn (backend) processes..." -ForegroundColor Cyan
    foreach ($proc in $uvicornProcesses)
    {
        Write-Host "  Killing process: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $proc.Id -Force
    }
    Write-Host "Uvicorn processes stopped" -ForegroundColor Green
}
else
{
    Write-Host "  No uvicorn processes found" -ForegroundColor Gray
}

# Kill Python processes running neuroglancer-chat
$pythonProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($pythonProcesses)
{
    Write-Host "Stopping Python processes..." -ForegroundColor Cyan
    foreach ($proc in $pythonProcesses)
    {
        Write-Host "  Killing process: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Gray
        Stop-Process -Id $proc.Id -Force
    }
    Write-Host "Python processes stopped" -ForegroundColor Green
}
else
{
    Write-Host "  No Python processes found" -ForegroundColor Gray
}

# Check for processes using ports 8000 (backend) and 5006 (frontend)
Write-Host ""
Write-Host "Checking ports 8000 and 5006..." -ForegroundColor Cyan

$port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($port8000)
{
    $pid8000 = $port8000.OwningProcess | Select-Object -First 1
    Write-Host "  Killing process on port 8000 (PID: $pid8000)" -ForegroundColor Gray
    Stop-Process -Id $pid8000 -Force -ErrorAction SilentlyContinue
    Write-Host "Port 8000 freed" -ForegroundColor Green
}
else
{
    Write-Host "  Port 8000 is free" -ForegroundColor Gray
}

$port5006 = Get-NetTCPConnection -LocalPort 5006 -ErrorAction SilentlyContinue
if ($port5006)
{
    $pid5006 = $port5006.OwningProcess | Select-Object -First 1
    Write-Host "  Killing process on port 5006 (PID: $pid5006)" -ForegroundColor Gray
    Stop-Process -Id $pid5006 -Force -ErrorAction SilentlyContinue
    Write-Host "Port 5006 freed" -ForegroundColor Green
}
else
{
    Write-Host "  Port 5006 is free" -ForegroundColor Gray
}

Write-Host ""
Write-Host "All Neuroglancer-Chat processes stopped!" -ForegroundColor Green
Write-Host "You can now restart the app with start_backend.ps1 and start_panel.ps1" -ForegroundColor Yellow
