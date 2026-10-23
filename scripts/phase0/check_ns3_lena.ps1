<#
.SYNOPSIS
    SLA Guardian - Phase 0 ns-3 & 5G-LENA Verification Wrapper for Windows.
.DESCRIPTION
    Inspects host Windows environment, checks WSL distribution readiness,
    and safely delegates to scripts/phase0/check_ns3_lena.sh if an active Linux distro exists.
#>

$ErrorActionPreference = "Continue"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   SLA GUARDIAN - 5G-LENA / ns-3 SIMULATOR VERIFICATION (WIN)    " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$LogDir = Join-Path $PSScriptRoot "..\..\logs\phase0"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir "ns3_lena_verification_win.log"
"Verification timestamp: $(Get-Date -Format u)" | Out-File -FilePath $LogFile -Encoding utf8

Write-Host "`n[*] Step 1: Checking Native Windows 5G-LENA Feasibility..." -ForegroundColor Yellow
Write-Host "[-] Note: ns-3 and 5G-LENA are designed and officially supported on Linux/POSIX."
Write-Host "[-] Native MSVC/Windows builds of 5G-LENA are non-standard and require extensive CMake/MinGW porting."

Write-Host "`n[*] Step 2: Inspecting WSL2 Subsystem..." -ForegroundColor Yellow
$wslCmd = Get-Command "wsl" -ErrorAction SilentlyContinue

if (-not $wslCmd) {
    Write-Host "[-] WSL is not installed on this system." -ForegroundColor Red
    "WSL not installed" | Out-File -FilePath $LogFile -Append
    exit 1
}

# Query WSL distributions
$wslOutput = & wsl --list --verbose 2>&1
$wslOutputText = $wslOutput -join "`n"
Write-Host "WSL Distributions:"
Write-Host $wslOutputText

$hasLinuxDistro = $false
foreach ($line in $wslOutput) {
    if ($line -match "Ubuntu" -or $line -match "Debian") {
        $hasLinuxDistro = $true
        break
    }
}

if (-not $hasLinuxDistro) {
    Write-Host "`n[-] FAILED: No Ubuntu or Debian Linux distribution is registered in WSL2." -ForegroundColor Red
    Write-Host "    Current WSL distributions: Only docker-desktop or uninitialized."
    Write-Host "    ns-3 and 5G-LENA cannot be compiled or executed without a Linux environment."
    Write-Host "`n[!] VERDICT: SIMULATOR NOT INSTALLED (Case C). Exit code: 1" -ForegroundColor Magenta
    "VERDICT: SIMULATOR NOT INSTALLED (Case C). No Linux distribution registered in WSL." | Out-File -FilePath $LogFile -Append
    exit 1
}

Write-Host "`n[*] Step 3: Invoking check_ns3_lena.sh inside WSL2..." -ForegroundColor Yellow
$wslScriptPath = "/mnt/c/gcemhacks5.0/scripts/phase0/check_ns3_lena.sh"
& wsl bash $wslScriptPath
$rc = $LASTEXITCODE

Write-Host "`nWSL script completed with exit code: $rc"
exit $rc
