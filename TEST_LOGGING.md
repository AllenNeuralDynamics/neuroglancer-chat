# Test Debug Logging

After restarting the backend, run this command to test if debug logging is working:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/debug/test-logging | Select-Object -ExpandProperty Content | ConvertFrom-Json | ConvertTo-Json
```

Or simpler:
```powershell
curl http://127.0.0.1:8000/debug/test-logging
```

You should see in the backend console:
- 🧪 DEBUG log from test endpoint
- 🧪 INFO log from test endpoint  
- 🧪 WARNING log from test endpoint
- 🧪 _dbg() call from test endpoint

If you see all 4 messages, debug logging is working!
