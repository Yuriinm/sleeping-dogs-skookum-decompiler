@echo off
rem Decompiles selected functions of sdhdship.exe with Ghidra, without the full auto-analysis.
rem
rem Requirements: Ghidra 12+, a JDK it accepts, and PyGhidra
rem   (pip install --no-index -f "%GHIDRA_HOME%\Ghidra\Features\PyGhidra\pypkg\dist" pyghidra)
rem
rem Environment:
rem   GHIDRA_HOME   Ghidra install folder (required)
rem   SD_EXE        path to sdhdship.exe (required)
rem   GHIDRA_PROJ   folder for the Ghidra project (default: %TEMP%\sdskoo_ghidra)
rem
rem Usage: decompile.bat <output.c> <depth> <rva>[=name] ...
rem The first run imports the exe into the project (no analysis); later runs reuse it.
if "%GHIDRA_HOME%"=="" ( echo Set GHIDRA_HOME to your Ghidra folder. & exit /b 1 )
if "%SD_EXE%"=="" ( echo Set SD_EXE to the path of sdhdship.exe. & exit /b 1 )
if "%GHIDRA_PROJ%"=="" set "GHIDRA_PROJ=%TEMP%\sdskoo_ghidra"
if not exist "%GHIDRA_PROJ%" mkdir "%GHIDRA_PROJ%"
set "SCRIPTS=%~dp0"
if not exist "%GHIDRA_PROJ%\SDSkoo.gpr" (
  python -m pyghidra.ghidra_launch --install-dir "%GHIDRA_HOME%" ghidra.app.util.headless.AnalyzeHeadless "%GHIDRA_PROJ%" SDSkoo -import "%SD_EXE%" -noanalysis
)
python -m pyghidra.ghidra_launch --install-dir "%GHIDRA_HOME%" ghidra.app.util.headless.AnalyzeHeadless "%GHIDRA_PROJ%" SDSkoo -process sdhdship.exe -noanalysis -scriptPath "%SCRIPTS%." -postScript DecompileTargets.py %*
