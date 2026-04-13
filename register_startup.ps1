$TaskName    = "StockManager-AutoStart"
$VbsPath     = "C:\Users\infolab\ws\stock-manager\start_stock_manager.vbs"
$Description = "Zaikokanri system auto-start at logon"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Argument = """" + $VbsPath + """"

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $Argument
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description $Description -Force

Write-Host ""
Write-Host ("登録完了: タスク名 = " + $TaskName) -ForegroundColor Green
Write-Host "次回 Windows ログオン時に自動起動します。"
Write-Host ""
Write-Host "手動で今すぐ起動する場合:"
Write-Host ("  Start-ScheduledTask -TaskName " + $TaskName)
Write-Host ""
Write-Host "タスクを削除する場合:"
Write-Host ("  Unregister-ScheduledTask -TaskName " + $TaskName + " -Confirm:false")
