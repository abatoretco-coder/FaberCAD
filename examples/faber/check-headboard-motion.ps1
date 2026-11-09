param(
    [string]$Design = 'target/headboard-comparison/headboard-assembly.sc',
    [string]$Cli = 'target/debug/solidcraft-cli.exe'
)
$ErrorActionPreference = 'Stop'
$outputDirectory = 'target/headboard-comparison'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $Cli run "$PSScriptRoot/motion-collision-reference.json" --results --json-out "$outputDirectory/reference-results.json"
if ($LASTEXITCODE -ne 0) { throw 'Analytic collision reference failed' }
$reference = @(Get-Content "$outputDirectory/reference-results.json" -Raw | ConvertFrom-Json)
$clear = $reference[10]
$collision = $reference[12]
if ($clear.clear -ne $true -or $clear.truncated -ne $false -or @($clear.collisions).Count -ne 0) { throw 'Known-clear reference failed' }
if ($collision.truncated -ne $false -or $collision.clear -ne $false -or @($collision.collisions).Count -ne 1) { throw 'Known-colliding reference failed' }
$hit = $collision.collisions[0]
if ($hit.first_step -ne 11 -or [Math]::Abs($hit.volume_mm3 - 500) -gt 0.001) { throw 'Collision onset or volume disagrees with analytic reference' }
& $Cli run "$PSScriptRoot/headboard-motion-check.json" --in $Design --results --json-out "$outputDirectory/collision-results.json"
if ($LASTEXITCODE -ne 0) { throw 'Motion collision command failed' }
$checks = @(Get-Content "$outputDirectory/collision-results.json" -Raw | ConvertFrom-Json)
if ($checks.Count -ne 2) { throw 'Expected structure and moving-part checks' }
foreach ($check in $checks) {
    if ($check.truncated -ne $false -or $check.samples -ne 41 -or $check.pairs -lt 1) {
        throw 'Collision qualification incomplete; do not report this assembly as clear'
    }
    if ($check.clear -and @($check.collisions).Count -gt 0) { throw 'Inconsistent clear result' }
}
& $Cli run "$PSScriptRoot/headboard-animation.json" --in $Design --results --json-out "$outputDirectory/animation-results.json"
if ($LASTEXITCODE -ne 0) { throw 'Motion animation command failed' }
$animation = @(Get-Content "$outputDirectory/animation-results.json" -Raw | ConvertFrom-Json)[0]
if ($animation.frames -ne 31 -or $animation.bytes -le 0 -or !(Test-Path -LiteralPath $animation.path)) { throw 'Animation artifact missing or incomplete' }
[pscustomobject]@{
    completed_checks = $checks.Count
    colliding_pairs = ($checks | ForEach-Object { @($_.collisions).Count } | Measure-Object -Sum).Sum
    assembly_clear = @($checks | Where-Object { !$_.clear }).Count -eq 0
    animation_frames = $animation.frames
    animation = $animation.path
}
