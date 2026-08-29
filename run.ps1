$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $Pythonw)) {
    Write-Error '先に setup.ps1 を実行してください。'
    exit 1
}
Start-Process -FilePath $Pythonw -ArgumentList ('"' + (Join-Path $ProjectDir 'app.pyw') + '"') -WorkingDirectory $ProjectDir
