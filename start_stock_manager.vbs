' コンソールウィンドウを表示せずに start_stock_manager.bat を起動するラッパー
' タスクスケジューラやスタートアップフォルダから呼び出す

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c ""C:\Users\infolab\ws\stock-manager\start_stock_manager.bat""", 0, False
