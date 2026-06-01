@echo off
mode con: cols=68 lines=14
REM ============================================================
REM  WEB DIR MAP — Build script para Windows
REM ============================================================
REM  Requisitos (apenas na sua maquina, NAO no PC do usuario final):
REM    - Node.js >= 16     https://nodejs.org
REM    - Python  >= 3.8    https://python.org
REM
REM  Saida:
REM    dist\WEB-DIR-MAP-1.0.0-x64.exe         (installer NSIS)
REM    dist\WEB-DIR-MAP-1.0.0-x64.portable.exe (portavel)
REM ============================================================

setlocal

echo.
echo [1/4] Instalando dependencias Node...
call npm install
if errorlevel 1 goto err

echo.
echo [2/4] Instalando PyInstaller + libs Python...
pip install pyinstaller requests beautifulsoup4 lxml
if errorlevel 1 goto err

echo.
echo [3/4] Empacotando Python em bin\web_dir_mapper.exe...
call npm run build-python
if errorlevel 1 goto err

echo.
echo [4/4] Buildando Electron Windows (NSIS + portable)...
call npm run build-win
if errorlevel 1 goto err

echo.
echo ============================================================
echo BUILD CONCLUIDO
echo Veja a pasta:  dist\
echo ============================================================
exit /b 0

:err
echo.
echo ============================================================
echo  ERRO no build. Veja a mensagem acima.
echo ============================================================
exit /b 1
