@echo off
"D:\python\anaconda\envs\th123\python.exe" -B -X utf8 "%~dp0launch.py" start %*
if errorlevel 1 pause
