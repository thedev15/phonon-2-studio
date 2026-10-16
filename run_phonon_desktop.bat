@echo off
setlocal
cd /d "%~dp0"
if not exist ".phonon-venv\Scripts\python.exe" (
  echo Phonon environment not found. Run:
  echo   python -m venv .phonon-venv
  echo   .phonon-venv\Scripts\python.exe -m pip install fermion-research
  pause
  exit /b 1
)
".phonon-venv\Scripts\python.exe" phonon_desktop.py
