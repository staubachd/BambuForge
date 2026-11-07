# Run every test, each against a fresh copy of the database, and report
# pass/fail explicitly. Silence is not a pass.
#
# The tests run against a COPY of the app in a scratch folder, so a test that
# writes cannot touch the real telemetry.db. The tests themselves used to live
# in that scratch folder too, under %TEMP% - which is where Windows eventually
# deletes things it has not touched in a while, and about twenty of them went
# that way. They live beside the project now; only the scratch copy is
# disposable.
#
# Every test gets a time limit (-TimeoutSec, default 30). A test that hangs -
# waiting on a network, a lock, a prompt - is killed with its whole process
# tree and counted as TIMEOUT, instead of stalling the run with no sign of
# which test it is.
param([int]$TimeoutSec = 30)

# Run one program, capture stdout+stderr, give up after $TimeoutSec.
function Invoke-Test([string]$exe, [string]$file, [string]$dir) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = (Get-Command $exe).Source
    $psi.Arguments              = '"' + $file + '"'
    $psi.WorkingDirectory       = $dir
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $p  = [System.Diagnostics.Process]::Start($psi)
    $so = $p.StandardOutput.ReadToEndAsync()
    $se = $p.StandardError.ReadToEndAsync()
    $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) {
        & taskkill.exe /T /F /PID $p.Id 2>&1 | Out-Null
        $p.WaitForExit(5000) | Out-Null
    } else {
        $p.WaitForExit()           # flush the async readers
    }
    $text = $so.Result + $se.Result
    [pscustomobject]@{
        TimedOut = $timedOut
        Code     = $(if ($timedOut) { $null } else { $p.ExitCode })
        Lines    = @($text -split "`r?`n" | Where-Object { $_ -ne "" })
        Text     = $text
    }
}

# One result line per test, plus the tail of its output when it did not pass.
function Write-Result([string]$name, $r, [bool]$ok) {
    $verdict = if ($r.TimedOut) { "TIMEOUT (${TimeoutSec}s)" } elseif ($ok) { "pass" } else { "FAIL" }
    "{0,-18} {1}" -f $name, $verdict
    if (-not $ok) { $r.Lines | Select-Object -Last 4 | ForEach-Object { "      $_" } }
}

$src = Split-Path -Parent $PSScriptRoot
$b   = Join-Path $env:TEMP "bambu-tests"
New-Item -ItemType Directory -Force $b | Out-Null
# The tests are COPIED into the scratch folder so they can import the app copy
# beside them, which means "the source, relative to me" would resolve to the
# scratch folder's parent. This is the authority instead.
$env:BAMBU_SRC = $src
Copy-Item "$PSScriptRoot\t_*.py" $b -Force
Copy-Item "$PSScriptRoot\t_*.js" $b -Force
Copy-Item "$src\*.py" $b -Force
Copy-Item "$src\dashboard.html" $b -Force
Copy-Item "$src\setup.html" $b -Force
# The app is configured by instance/db.json now, not by a config file, and every
# setting rides along inside the telemetry.db each test starts from. A stray
# printer.config.json here would make the wizard tests think this is an upgrade.
Remove-Item "$b\printer.config.json" -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$b\instance" | Out-Null
# no BOM: Out-File -Encoding utf8 writes one in Windows PowerShell 5.1
[IO.File]::WriteAllText("$b\instance\db.json",
    '{ "backend": "sqlite", "sqlite_path": "telemetry.db" }')
New-Item -ItemType Directory -Force "$b\samples" | Out-Null
Copy-Item "$src\samples\*" "$b\samples" -Force
New-Item -ItemType Directory -Force "$b\tools" | Out-Null
Copy-Item "$src\tools\*.py" "$b\tools" -Force

$fail = 0
$here = (Get-Location).Path
foreach ($f in Get-ChildItem "$b\t_*.py" | Sort-Object Name) {
    Copy-Item "$src\telemetry.db" $b -Force        # every test starts clean
    $r  = Invoke-Test py $f.FullName $here
    $ok = ($r.Code -eq 0) -and $r.Text -match '(?m)^ok\s*$'
    if (-not $ok) { $fail++ }
    Write-Result $f.Name $r $ok
}
foreach ($f in Get-ChildItem "$b\t_*.js" | Sort-Object Name) {
    $r  = Invoke-Test node $f.FullName $here
    $ok = $r.Code -eq 0
    if (-not $ok) { $fail++ }
    Write-Result $f.Name $r $ok
}
foreach ($m in "filament_catalog.py", "bambu_state.py", "gcode_meta.py", "makerworld.py") {
    $r  = Invoke-Test py (Join-Path $src $m) $src
    $ok = $r.Code -eq 0
    if (-not $ok) { $fail++ }
    Write-Result $m $r $ok
}
""
if ($fail) { "$fail FAILED" } else { "all green" }
