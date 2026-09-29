; Instalador de Servidor Home (se compila con NSIS: makensis instalador.nsi)
Target amd64-unicode
ManifestDPIAware true
!define APPNAME "Servidor Home"
!define APPVERSION "2.5.5"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ServidorHome"

Name "${APPNAME}"
!ifndef OUTFILE
  !define OUTFILE "Instalar Servidor Home.exe"
!endif
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\Servidor Home"
InstallDirRegKey HKCU "${UNINSTKEY}" "InstallLocation"
SetCompressor /SOLID lzma
BrandingText "${APPNAME} ${APPVERSION}"
ShowInstDetails hide
ShowUninstDetails hide

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON "app\web\icono.ico"
!define MUI_UNICON "app\web\icono.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "instalador.bmp"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar Servidor Home"
!define MUI_WELCOMEPAGE_TEXT "Servidor Home enciende un servidor de Minecraft en este PC y te da una dirección fija de playit.gg para que tus amigos entren desde cualquier lugar.$\r$\n$\r$\nTus servidores y mundos quedarán en Documentos\servidor home.$\r$\n$\r$\nNo necesita permisos de administrador."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "Servidor Home está listo"
!define MUI_FINISHPAGE_TEXT "Lo encuentras en el menú Inicio y en el Escritorio como «Servidor Home»."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir Servidor Home"
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirApp
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

VIProductVersion "${APPVERSION}.0"
VIAddVersionKey /LANG=${LANG_SPANISH} "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=${LANG_SPANISH} "ProductVersion" "${APPVERSION}"
VIAddVersionKey /LANG=${LANG_SPANISH} "FileVersion" "${APPVERSION}"
VIAddVersionKey /LANG=${LANG_SPANISH} "FileDescription" "Instalador de ${APPNAME}"
VIAddVersionKey /LANG=${LANG_SPANISH} "LegalCopyright" "${APPNAME}"

Function AbrirApp
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\servidor_home.py"'
FunctionEnd

Section "Servidor Home"
  SetShellVarContext current
  ; Si ya estaba instalada y abierta, se cierra bien (los servidores se apagan guardando el mundo).
  IfFileExists "$INSTDIR\python\pythonw.exe" 0 sin_cerrar
    DetailPrint "Cerrando Servidor Home..."
    ExecWait '"$INSTDIR\python\pythonw.exe" "$INSTDIR\servidor_home.py" --cerrar'
  sin_cerrar:
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File "app\servidor_home.py"
  File "app\instalado.txt"
  File "app\README.md"
  SetOutPath "$INSTDIR\web"
  File "app\web\index.html"
  File "app\web\remoto.html"
  File "app\web\icono.svg"
  File "app\web\icono.ico"
  SetOutPath "$INSTDIR\python"
  File /r "app\python\*.*"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  CreateShortCut "$SMPROGRAMS\Servidor Home.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\servidor_home.py"' "$INSTDIR\web\icono.ico" 0 SW_SHOWNORMAL "" "Tu servidor de Minecraft en este PC"
  CreateShortCut "$DESKTOP\Servidor Home.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\servidor_home.py"' "$INSTDIR\web\icono.ico" 0 SW_SHOWNORMAL "" "Tu servidor de Minecraft en este PC"
  CreateDirectory "$DOCUMENTS\servidor home"

  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${APPVERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\web\icono.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\python\pythonw.exe" 0 sin_cerrar
    ExecWait '"$INSTDIR\python\pythonw.exe" "$INSTDIR\servidor_home.py" --cerrar'
  sin_cerrar:
  Delete "$SMPROGRAMS\Servidor Home.lnk"
  Delete "$DESKTOP\Servidor Home.lnk"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\web"
  Delete "$INSTDIR\servidor_home.py"
  Delete "$INSTDIR\instalado.txt"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  MessageBox MB_YESNO|MB_ICONQUESTION "¿Borrar también los datos de la app (Java descargado, vínculo con playit.gg y ajustes de la ventana)?$\r$\n$\r$\nTus servidores y mundos en Documentos\servidor home no se borran." /SD IDNO IDNO fin
    RMDir /r "$LOCALAPPDATA\Servidor Home"
  fin:
SectionEnd
