# One-time setup for the laptop Reddit pull. Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File laptop\install_task.ps1
# Re-run it after moving the project folder. Remove with:
#   Unregister-ScheduledTask -TaskName DepthWallpaperRedditPull -Confirm:$false

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
# Short venv path: onnx/playwright DLLs fail under long Windows paths.
$Venv = Join-Path $env:USERPROFILE ".dlw-laptop"  # outside AppData: packaged apps redirect AppData writes

if (-not (Test-Path "$Venv\Scripts\python.exe")) { py -3 -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install -q -r "$PSScriptRoot\requirements.txt"

$py = "$Venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$PSScriptRoot\reddit_pull.py`"" -WorkingDirectory $Project
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 9:30am),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "DepthWallpaperRedditPull" -Action $action -Trigger $triggers `
    -Settings $settings -Description "Saves EarthPorn-style photos to the wallpaper inbox" -Force | Out-Null
Write-Host "Installed. It runs at 9:30 and at login (once per day max)."
Write-Host "Test now: & '$Venv\Scripts\python.exe' '$PSScriptRoot\reddit_pull.py' --login   (then sign in once)"
