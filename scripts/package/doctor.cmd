@echo off
"%~dp0mcp\runtime\node.exe" "%~dp0mcp\dist\index.js" --doctor %*
exit /b %errorlevel%
