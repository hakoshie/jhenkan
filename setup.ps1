$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir '.venv'

if (-not (Test-Path (Join-Path $VenvDir 'Scripts\python.exe'))) {
    py -3 -m venv $VenvDir
}

& (Join-Path $VenvDir 'Scripts\python.exe') -m pip install --upgrade pip
& (Join-Path $VenvDir 'Scripts\python.exe') -m pip install -r (Join-Path $ProjectDir 'requirements.txt')

Write-Host ''
Write-Host 'JHenkanを起動します。設定画面でOpenAI APIキーを入力してください。'
Start-Process -FilePath (Join-Path $VenvDir 'Scripts\pythonw.exe') -ArgumentList ('"' + (Join-Path $ProjectDir 'app.pyw') + '"') -WorkingDirectory $ProjectDir
