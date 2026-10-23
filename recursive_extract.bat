@echo off
rem 用法一：把压缩包或文件夹拖到本文件图标上松手
rem 用法二：命令行运行 recursive_extract.bat 路径 [选项]
rem 不想结束时停顿看结果的话，删除最后的 pause 即可
setlocal
set "SCRIPT=%~dp0recursive_extract.py"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%SCRIPT%" %*
) else (
  python "%SCRIPT%" %*
)
echo.
pause
