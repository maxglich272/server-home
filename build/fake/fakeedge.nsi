; msedge.exe de prueba: anota la línea de comandos y "tiene la ventana abierta"
; hasta que la prueba crea cerrar-ventana.txt (simula que el usuario la cierra).
Target amd64-unicode
OutFile "msedge.exe"
SilentInstall silent
RequestExecutionLevel user
Section
  FileOpen $0 "$EXEDIR\edge-args.txt" a
  FileSeek $0 0 END
  FileWrite $0 "$CMDLINE$\r$\n"
  FileClose $0
  StrCpy $1 0
  espera:
    IfFileExists "$EXEDIR\cerrar-ventana.txt" listo
    Sleep 500
    IntOp $1 $1 + 1
    IntCmp $1 2400 listo espera listo
  listo:
  Delete "$EXEDIR\cerrar-ventana.txt"
SectionEnd
