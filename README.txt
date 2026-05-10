═══════════════════════════════════════════════════════════════
  OI FETCHER PRO v2.0 — Professional Windows Software
  Build & Installation Guide
═══════════════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FILES IN THIS FOLDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  oi_fetcher_pro.py       ← Main Python app (login + GUI + fetch)
  installer.nsi           ← NSIS installer script
  build.bat               ← ONE CLICK BUILD (run this!)
  README.txt              ← This file

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STEP 1 — PREPARE (one time only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Copy all files to:
     C:\Users\DeAL\OneDrive\Desktop\OI_Trader\

  2. (Optional) Add your icon:
     Create folder: assets\
     Put your icon: assets\icon.ico  (256x256 .ico file)
     Put banner:    assets\banner.bmp (164x314 pixels)
     (Without these, installer uses defaults)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STEP 2 — BUILD (double click)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Double-click: build.bat

  Yeh kya karega:
    ✓ Python dependencies install karega
    ✓ OI_Fetcher_Pro.exe banayega (PyInstaller)
    ✓ OI_Fetcher_Pro_Setup.exe banayega (NSIS)

  Time: ~3-5 minutes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STEP 3 — INSTALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Double-click: OI_Fetcher_Pro_Setup.exe

  Yeh kya karega:
    ✓ C:\Program Files\OI Fetcher Pro\ mein install hoga
    ✓ Start Menu mein shortcut banta hai
    ✓ Desktop pe shortcut banta hai
    ✓ Windows startup pe auto-start set hoga
    ✓ Add/Remove Programs mein dikhega

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STEP 4 — FIRST LOGIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  DEFAULT CREDENTIALS:
    Username: admin
    Password: admin123

  ⚠️  IMPORTANT: First login ke baad password change karo!
      App → Users button → Select admin → Reset Password

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  USER MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Admin account se:
    - Naaye users banao (client ya admin role)
    - Passwords reset karo
    - Users disable/enable karo
    - Users delete karo

  User Roles:
    admin  → Full access: fetch, settings, user management
    client → View only: signals table dekh sakte hain

  Client users ko share karo:
    - Software install karo unke PC pe
    - Username + Password batao

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STARTUP OPTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Auto-start (Windows boot pe):
    → Installer automatically set karta hai
    → Settings > Apps > Startup mein dekho

  Manual start:
    → Desktop shortcut
    → Start Menu → OI Fetcher Pro

  Disable auto-start:
    → Task Manager → Startup tab
    → OI Fetcher Pro → Disable

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TRADING SCHEDULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Active Hours:  11:00 AM — 11:00 PM
  Fetch Interval: Every 300 seconds (5 min)
  OI Filter:     BUY ≥ +1.0% | SELL ≤ -1.0%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MT5 TERMINALS CONFIGURED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Terminal 1: 30DFCE03904134F21E85FDA4A06D4D35
  Terminal 2: 4AB1FF510CA40454D57B5C02C860DEAE

  Dono mein automatically likhta hai:
    → oi_multi_data.json
    → oi_data.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  UNINSTALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Control Panel → Programs → OI Fetcher Pro → Uninstall
  Ya: Start Menu → OI Fetcher Pro → Uninstall

═══════════════════════════════════════════════════════════════
