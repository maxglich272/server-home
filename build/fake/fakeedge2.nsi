; msedge.exe de prueba (2): abre una ventana real con título «Servidor Home» y clase de Chromium.
Target amd64-unicode
OutFile "msedge.exe"
SilentInstall silent
RequestExecutionLevel user
Section
  ExecWait '"Z:\home\claude\win\py\python\pythonw.exe" "Z:\home\claude\build\fake\fakewin.py" $CMDLINE'
SectionEnd
