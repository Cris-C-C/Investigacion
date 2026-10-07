# PHOEBE Lab UI Startup Rule

When the user asks to "iniciar phoebe-lab.ui" (or variations of it), you must follow this exact sequence to start the application and open a session directly without passing through the dashboard:

1. Ensure the PHOEBE API server is running. If it isn't, start it as a background daemon process (`IsDaemon: true`) from the `c:\Users\darkm\Desktop\archivos_Investigación\Investigacion\phoebe-lab.ui` directory:
   ```powershell
   .\venv\Scripts\uvicorn.exe api.main:app --host 0.0.0.0 --port 8001 --reload --reload-dir api --reload-dir manager
   ```
2. Start a new UI session directly via the API and open it in the Brave browser by running this PowerShell command using `run_command`:
   ```powershell
   $res = Invoke-RestMethod -Uri "http://localhost:8001/dash/start-session" -Method Post
   $port = $res.port
   Start-Process brave "http://localhost:$port"
   Write-Output "Session started directly on port $port"
   ```
3. Inform the user that the session has been created and opened directly in Brave.
