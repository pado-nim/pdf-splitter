@echo off
chcp 65001 >nul
title PDF 분할기 설치
cd /d "%~dp0"
echo.
echo  ===== PDF 분할기 설치 =====
echo.

rem 1) 파이썬 찾기
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if defined PY (
  %PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul || set "PY="
)
if not defined PY (
  echo  [1/3] 파이썬이 없어서 설치합니다...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo.
    echo  자동 설치에 실패했어요. python.org 에서 파이썬을 설치한 뒤
    echo  설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하고 다시 실행해 주세요.
    start https://www.python.org/downloads/
    pause & exit /b 1
  )
  echo.
  echo  파이썬 설치 완료. 이 창을 닫고 "1_install.bat" 를 한 번 더 실행해 주세요.
  pause & exit /b 0
)
echo  [1/3] 파이썬 확인 완료
%PY% -c "import tkinter" >nul 2>nul || ( echo  파이썬에 tkinter 가 없어요. python.org 설치 파일로 다시 설치해 주세요. & pause & exit /b 1 )

rem 2) 필요한 패키지
echo  [2/3] 필요한 패키지 설치 중... ^(1~2분^)
%PY% -m pip install --upgrade --quiet pypdf
if errorlevel 1 ( echo  패키지 설치 실패. 인터넷 연결을 확인해 주세요. & pause & exit /b 1 )
rem  아래는 있으면 더 좋은 것들 (실패해도 프로그램은 돌아가요)
%PY% -m pip install --upgrade --quiet pikepdf     || echo   - 빠른 엔진^(pikepdf^) 설치 실패: 기본 엔진으로 동작해요
%PY% -m pip install --upgrade --quiet pypdfium2 pillow || echo   - 미리보기 도구 설치 실패: 미리보기 없이 동작해요
%PY% -m pip install --upgrade --quiet tkinterdnd2 || echo   - 끌어다 놓기 설치 실패: 클릭해서 파일을 고르면 돼요

rem 3) 바로가기 (바탕화면 + 우클릭 "보내기" 메뉴)
echo  [3/3] 바로가기 만드는 중...
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('SendTo'))){" ^
  " $s=$w.CreateShortcut((Join-Path $d 'PDF 분할기.lnk'));" ^
  " $s.TargetPath='%PYW%'; $s.Arguments='\"%~dp0app.py\"'; $s.WorkingDirectory='%~dp0';" ^
  " $s.IconLocation='%~dp0icon.ico'; $s.Save() }" >nul 2>nul

echo.
echo  ===== 설치 완료! =====
echo  바탕화면의 "PDF 분할기" 또는 이 폴더의 "2_run.bat" 로 켜세요.
echo  PDF 를 우클릭 ^> 보내기 ^> "PDF 분할기" 로 바로 열 수도 있어요.
echo.
pause
