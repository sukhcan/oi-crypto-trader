; ═══════════════════════════════════════════════════════════════
;  OI Fetcher Pro v2.0 — NSIS Installer
;  Fixed: No icon/bitmap dependency — pure wizard UI
; ═══════════════════════════════════════════════════════════════

Unicode True

!define APP_NAME      "OI Fetcher Pro"
!define APP_VER       "2.0"
!define APP_EXE       "OI_Fetcher_Pro.exe"
!define APP_PUBLISHER "OI Trader Systems"
!define INST_DIR      "$PROGRAMFILES64\OI Fetcher Pro"
!define REG_UNINST    "Software\Microsoft\Windows\CurrentVersion\Uninstall\OIFetcherPro"
!define REG_RUN       "Software\Microsoft\Windows\CurrentVersion\Run"

Name              "${APP_NAME} v${APP_VER}"
OutFile           "OI_Fetcher_Pro_Setup.exe"
InstallDir        "${INST_DIR}"
InstallDirRegKey  HKLM "${REG_UNINST}" "InstallLocation"
RequestExecutionLevel admin
SetCompressor     /SOLID lzma
BrandingText      "${APP_NAME} v${APP_VER}"

!include "MUI2.nsh"
!include "LogicLib.nsh"

; ── MUI Settings
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Cancel installation?"

!define MUI_WELCOMEPAGE_TITLE   "Welcome to ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT    "This will install ${APP_NAME} v${APP_VER} on your computer.$\r$\n$\r$\nFeatures:$\r$\n  - Auto CFTC OI data fetch$\r$\n  - MT5 signal delivery$\r$\n  - Login protection$\r$\n  - Windows auto-start$\r$\n$\r$\nClick Next to continue."

!define MUI_FINISHPAGE_TITLE    "Installation Complete!"
!define MUI_FINISHPAGE_TEXT     "${APP_NAME} v${APP_VER} installed successfully!$\r$\n$\r$\nDefault Login:$\r$\n  Username: admin$\r$\n  Password: admin123$\r$\n$\r$\nChange password after first login:$\r$\nApp > Users > Reset Password"
!define MUI_FINISHPAGE_RUN      "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch OI Fetcher Pro"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE    "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

VIProductVersion  "2.0.0.0"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductVersion"  "${APP_VER}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileVersion"     "2.0.0.0"
VIAddVersionKey /LANG=${LANG_ENGLISH} "LegalCopyright"  "2026 ${APP_PUBLISHER}"

; ══════════════════════════════════════════════════════════════
Section "Main" SEC_MAIN
    SectionIn RO
    SetOutPath  "$INSTDIR"
    SetOverwrite on

    File "dist\${APP_EXE}"
    CreateDirectory "$INSTDIR\data"
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Add/Remove Programs
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayName"     "${APP_NAME}"
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayVersion"  "${APP_VER}"
    WriteRegStr   HKLM "${REG_UNINST}" "Publisher"       "${APP_PUBLISHER}"
    WriteRegStr   HKLM "${REG_UNINST}" "InstallLocation" "$INSTDIR"
    WriteRegStr   HKLM "${REG_UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
    WriteRegDWORD HKLM "${REG_UNINST}" "NoModify"        1
    WriteRegDWORD HKLM "${REG_UNINST}" "NoRepair"        1
    WriteRegStr   HKLM "${REG_UNINST}" "EstimatedSize"   "50000"

    ; Start Menu
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut  "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"        "$INSTDIR\${APP_EXE}"
    CreateShortcut  "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"           "$INSTDIR\Uninstall.exe"

    ; Desktop
    CreateShortcut  "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

    ; Windows Startup
    WriteRegStr HKCU "${REG_RUN}" "OIFetcherPro" '"$INSTDIR\${APP_EXE}"'
SectionEnd

; ══════════════════════════════════════════════════════════════
Section "Uninstall"
    DeleteRegValue HKCU "${REG_RUN}" "OIFetcherPro"
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\Uninstall.exe"

    MessageBox MB_YESNO|MB_ICONQUESTION \
        "Delete all user data (accounts, logs)?" \
        IDNO skip_data
    RMDir /r "$INSTDIR\data"
    skip_data:

    RMDir  "$INSTDIR"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
    RMDir  "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKLM "${REG_UNINST}"
SectionEnd
