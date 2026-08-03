param(
  [Parameter(Mandatory = $false)]
  [string[]]$SourcePath = @(),

  [Parameter(Mandatory = $false)]
  [string]$OutputRoot = ""
)

$ErrorActionPreference = 'Stop'
$generator = Join-Path $PSScriptRoot '..\scripts\generate_gradebook.ps1'

try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
} catch {
  [pscustomobject]@{
    status = 'skipped'
    reason = 'Microsoft Excel COM is unavailable on this machine.'
    cases = @()
  } | ConvertTo-Json -Depth 5
  exit 0
}

if ($SourcePath.Count -eq 0) {
  throw 'Provide one or more -SourcePath values to run the local Excel COM integration test.'
}
if (-not $OutputRoot) {
  $OutputRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('gradebook-com-integration-' + [guid]::NewGuid().ToString('N'))
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$cases = @()
for ($index = 0; $index -lt $SourcePath.Count; $index++) {
  $source = (Resolve-Path -LiteralPath $SourcePath[$index]).Path
  $output = Join-Path $OutputRoot ('case-' + ($index + 1))
  & powershell -NoProfile -ExecutionPolicy Bypass -File $generator -SourcePath $source -OutputDir $output
  if ($LASTEXITCODE -ne 0) {
    throw "Excel COM generation failed for $source"
  }
  $qa = Join-Path $output 'qa-report.json'
  if (-not (Test-Path -LiteralPath $qa)) {
    throw "QA report was not created for $source"
  }
  $report = Get-Content -LiteralPath $qa -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$report.status -ne 'passed' -or [string]$report.anchor_mode -ne 'excel_named_range') {
    throw "Named-range QA did not pass for $source"
  }
  $cases += [pscustomobject]@{
    source = $source
    output = $output
    status = [string]$report.status
    variant = [string]$report.named_range_variant
    preserved_named_range_count = [int]$report.preserved_named_range_count
    capacity_end = [int]$report.checks.named_ranges.xlsx.locations.gb_data_table.max_row
  }
}

[pscustomobject]@{
  status = 'passed'
  output_root = $OutputRoot
  cases = $cases
} | ConvertTo-Json -Depth 8
