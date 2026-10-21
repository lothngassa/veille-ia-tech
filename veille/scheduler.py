"""Tâche planifiée Windows : envoi quotidien à l'heure choisie, et rattrapage à l'ouverture de session."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from .config import ROOT, TASK_NAME, parse_send_time

SCRIPT = ROOT / "veille.py"


class SchedulerError(Exception):
    pass


def _run_powershell(script: str) -> str:
    """Exécute un script PowerShell encodé (aucun souci de guillemets, d'espaces ou d'accents dans les chemins)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip().splitlines()
        raise SchedulerError(message[0] if message else f"PowerShell a échoué (code {proc.returncode})")
    return proc.stdout.strip()


def _ps(value: str) -> str:
    """Chaîne PowerShell entre apostrophes."""
    return "'" + str(value).replace("'", "''") + "'"


def pythonw_executable() -> str:
    """pythonw.exe exécute le script sans ouvrir de fenêtre noire."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def install(send_time: str, task_name: str = TASK_NAME) -> None:
    hour, minute = parse_send_time(send_time)
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute {_ps(pythonw_executable())} -Argument {_ps(f'"{SCRIPT}" auto')} -WorkingDirectory {_ps(ROOT)}
$daily = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours({hour}).AddMinutes({minute}))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT2M'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName {_ps(task_name)} -Action $action -Trigger @($daily, $logon) -Settings $settings `
    -Principal $principal -Force `
    -Description 'Veille IA & Tech : brief quotidien sur Telegram ({hour:02d}:{minute:02d}), rattrapage au démarrage du PC.' | Out-Null
"""
    _run_powershell(script)


def uninstall(task_name: str = TASK_NAME) -> bool:
    script = f"""
$t = Get-ScheduledTask -TaskName {_ps(task_name)} -ErrorAction SilentlyContinue
if ($t) {{ Unregister-ScheduledTask -TaskName {_ps(task_name)} -Confirm:$false; 'removed' }} else {{ 'absent' }}
"""
    return _run_powershell(script) == "removed"


def status(task_name: str = TASK_NAME) -> dict | None:
    """État de la tâche : None si elle n'existe pas."""
    script = f"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = Get-ScheduledTask -TaskName {_ps(task_name)} -ErrorAction SilentlyContinue
if (-not $t) {{ 'null'; exit 0 }}
$i = $t | Get-ScheduledTaskInfo
$fmt = {{ param($d) if ($d -and $d.Year -gt 2000) {{ $d.ToString('yyyy-MM-dd HH:mm') }} else {{ $null }} }}
[pscustomobject]@{{
    state = [string]$t.State
    next_run = & $fmt $i.NextRunTime
    last_run = & $fmt $i.LastRunTime
    last_result = $i.LastTaskResult
}} | ConvertTo-Json -Compress
"""
    out = _run_powershell(script)
    return json.loads(out) if out and out != "null" else None
