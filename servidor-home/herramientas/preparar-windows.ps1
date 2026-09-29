# Servidor Home: prepara Python y los accesos directos en Windows (lo llama «Servidor Home.bat»).
param([switch]$Python, [switch]$Accesos)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
$tools = $PSScriptRoot
$app = Split-Path -Parent $tools

if ($Python) {
  $dest = Join-Path $app 'python'
  $arch = 'amd64'
  if ($env:PROCESSOR_ARCHITECTURE -eq 'x86' -and -not $env:PROCESSOR_ARCHITEW6432) { $arch = 'win32' }
  $sources = @(@{ Url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-$arch.zip"; Kind = 'zip' })
  if ($arch -eq 'amd64') {
    $sources += @{ Url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14+20260901-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'; Kind = 'tar.gz' }
  }
  $ok = $false
  foreach ($s in $sources) {
    try {
      Write-Host "Descargando Python ($($s.Url)) ..."
      $tmp = Join-Path $env:TEMP ('servidor-home-python.' + $s.Kind)
      Invoke-WebRequest -UseBasicParsing -Uri $s.Url -OutFile $tmp
      if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
      if ($s.Kind -eq 'zip') { Expand-Archive -Force -Path $tmp -DestinationPath $dest }
      else { & tar.exe -xzf $tmp -C $app }      # el paquete trae la carpeta "python"
      Remove-Item -Force $tmp -ErrorAction SilentlyContinue
      if (Test-Path (Join-Path $dest 'pythonw.exe')) { $ok = $true; break }
    } catch {
      Write-Host "No resultó: $($_.Exception.Message)"
    }
  }
  if ($ok) { Write-Host 'Python listo.' } else { exit 1 }
}

if ($Accesos) {
  try {
    $ws = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
      if (-not $dir -or -not (Test-Path $dir)) { continue }
      $lnk = $ws.CreateShortcut((Join-Path $dir 'Servidor Home.lnk'))
      $lnk.TargetPath = Join-Path $app 'Servidor Home.bat'
      $lnk.WorkingDirectory = $app
      $lnk.IconLocation = (Join-Path $app 'web\icono.ico') + ',0'
      $lnk.WindowStyle = 7
      $lnk.Description = 'Tu servidor de Minecraft en este PC'
      $lnk.Save()
    }
    Set-Content -Path (Join-Path $tools '.accesos-listos') -Value ($app + '\')
    Write-Host 'Accesos directos listos en el Escritorio y en el menú Inicio.'
  } catch {
    Write-Host "No se pudieron crear los accesos directos: $($_.Exception.Message)"
  }
}
