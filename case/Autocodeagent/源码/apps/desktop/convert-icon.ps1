# 转换 PNG 到 ICO 脚本
param(
    [string]$InputPath = "build\logo.png",
    [string]$OutputPath = "build\icon.ico"
)

Add-Type -AssemblyName System.Drawing

$bitmap = [System.Drawing.Bitmap]::FromFile((Resolve-Path $InputPath))
$icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())

$stream = [System.IO.FileStream]::new($OutputPath, [System.IO.FileMode]::Create)
$icon.Save($stream)
$stream.Close()

Write-Host "Icon created: $OutputPath"
