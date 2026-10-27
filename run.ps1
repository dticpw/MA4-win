param(
    [ValidateSet("start", "stop", "backend", "web", "terminal")]
    [string]$Component = "start",
    [string]$Config = (Join-Path $PSScriptRoot "config.json"),
    [string]$ThreadId = "",
    [string]$WorkingDirectory = $PSScriptRoot,
    [switch]$IncludeBackend,
    [switch]$NoBrowser
)
# This launcher does not install anything or change the execution policy.
$ma4Python = "D:/python/anaconda/envs/th123/python.exe"
$ma4Args = @("-B", "-X", "utf8", (Join-Path $PSScriptRoot "launch.py"), $Component, "--config", $Config)
if ($Component -eq "terminal") {
    $ma4Args += @("--cwd", $WorkingDirectory)
    if ($ThreadId) { $ma4Args += @("--thread-id", $ThreadId) }
}
if ($IncludeBackend) { $ma4Args += "--include-backend" }
if ($NoBrowser) { $ma4Args += "--no-browser" }
& $ma4Python @ma4Args
exit $LASTEXITCODE
