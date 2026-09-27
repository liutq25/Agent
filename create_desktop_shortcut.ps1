$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = (Get-Command python).Source
$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { $pythonwPath = $pythonPath }
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop '知学 CogniTutor-DS.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + (Join-Path $projectDir 'launch_agent.py') + '"'
$shortcut.WorkingDirectory = $projectDir
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,77"
$shortcut.Description = 'Start CogniTutor-DS'
$shortcut.Save()
Write-Output $shortcutPath
