$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Remove-ItemProperty -Path $RunKey -Name 'JHenkan' -ErrorAction SilentlyContinue
Write-Host 'JHenkanの自動起動を解除しました。ファイルとAPIキーは削除していません。'
