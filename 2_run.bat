@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( echo 먼저 "1_install.bat" 를 실행해 주세요. & pause & exit /b 1 )
%PY% -c "import pypdf" >nul 2>nul || ( echo 먼저 "1_install.bat" 를 실행해 주세요. & pause & exit /b 1 )
where pyw >nul 2>nul && ( start "" pyw -3 "%~dp0app.py" %* & exit /b 0 )
where pythonw >nul 2>nul && ( start "" pythonw "%~dp0app.py" %* & exit /b 0 )
%PY% "%~dp0app.py" %*
