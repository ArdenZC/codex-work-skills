param(
  [Parameter(Mandatory=$true)]
  [string]$SourcePath,

  [Parameter(Mandatory=$false)]
  [string]$OutputDir = "",

  [Parameter(Mandatory=$false)]
  [string]$TemplatePath = "",

  [Parameter(Mandatory=$false)]
  [string]$ManifestPath = "",

  [Parameter(Mandatory=$false)]
  [string]$SchemaPath = "",

  [Parameter(Mandatory=$false)]
  [switch]$SkipTemplateValidation,

  [Parameter(Mandatory=$false)]
  [switch]$SkipOutputValidation,

  [Parameter(Mandatory=$false)]
  [string]$QaReportPath = "",

  [Parameter(Mandatory=$false)]
  [string]$OutputFile = ""
)

$ErrorActionPreference = 'Stop'

if (-not $SchemaPath) {
  $SchemaPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'schemas\gradebook-input.schema.json'
}

function Get-PythonCommand() {
  if ($env:CODEX_PYTHON -and (Test-Path -LiteralPath $env:CODEX_PYTHON)) { return $env:CODEX_PYTHON }
  if ($env:PYTHON -and (Test-Path -LiteralPath $env:PYTHON)) { return $env:PYTHON }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python -and $python.Source -notlike '*WindowsApps*') { return $python.Source }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return $py.Source }
  throw "Python is required to read manifest.yaml and run output validation."
}

$PythonCommand = Get-PythonCommand
$ManifestToJson = Join-Path $PSScriptRoot 'manifest_to_json.py'
$ManifestJsonPath = Join-Path ([System.IO.Path]::GetTempPath()) ("gradebook-manifest-" + [guid]::NewGuid().ToString('N') + '.json')
$manifestArgs = @('--output', $ManifestJsonPath)
if ($ManifestPath) { $manifestArgs += @('--manifest', $ManifestPath) }
if ($TemplatePath) { $manifestArgs += @('--template', $TemplatePath) }
try {
  & $PythonCommand $ManifestToJson @manifestArgs
  if ($LASTEXITCODE -ne 0) {
    throw 'Could not resolve the gradebook template package manifest and fingerprint.'
  }
  $ManifestData = (Get-Content -LiteralPath $ManifestJsonPath -Raw -Encoding UTF8) | ConvertFrom-Json
} finally {
  Remove-Item -LiteralPath $ManifestJsonPath -Force -ErrorAction SilentlyContinue
}
$ManifestPath = [string]$ManifestData.manifest_path

function Assert-ManifestCompatibility($manifest) {
  $version = [string]$manifest.template.version
  if (-not $version -or $version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
    throw 'Manifest must declare an ASCII semantic template version without leading zeros'
  }
  try {
    [int]$major = $version.Split('.')[0]
    [int]$minor = $version.Split('.')[1]
  } catch {
    throw 'Manifest must declare an ASCII semantic template version without leading zeros'
  }
  $supportedMajor = 1
  $supportedMinors = @(0, 1)
  if ($major -ne $supportedMajor) {
    throw "Unsupported template major version $major; supported major is $supportedMajor"
  }
  if ($minor -notin $supportedMinors) {
    throw "Unsupported template minor version $minor; supported minors are 0 and 1"
  }
  if ($null -eq $manifest.generator.supported_major) {
    throw 'Manifest must declare generator.supported_major'
  }
  try {
    [int]$declaredMajor = $manifest.generator.supported_major
  } catch {
    throw 'Manifest generator.supported_major must be an integer'
  }
  if ($declaredMajor -ne $supportedMajor) {
    throw "Manifest generator.supported_major must remain $supportedMajor; it does not define support"
  }
  if ([string]$manifest.anchor_mode -notin @('legacy_coordinates', 'excel_named_range')) {
    throw "Unsupported gradebook anchor mode: $($manifest.anchor_mode)"
  }
  if ($version -match '^1\.0\.' -and [string]$manifest.anchor_mode -ne 'legacy_coordinates') {
    throw 'Template version 1.0.x must use legacy_coordinates.'
  }
  if ($version -match '^1\.1\.' -and [string]$manifest.anchor_mode -ne 'excel_named_range') {
    throw 'Template version 1.1.x must use excel_named_range.'
  }
}

Assert-ManifestCompatibility $ManifestData

$TemplateWasProvided = [bool]$TemplatePath
if (-not $TemplatePath) {
  $TemplatePath = [string]$ManifestData.template_path
}

if (-not (Test-Path -LiteralPath $TemplatePath)) {
  throw "Template not found: $TemplatePath"
}

& $PythonCommand (Join-Path $PSScriptRoot 'validate_template.py') --identity-only --template $TemplatePath --manifest $ManifestPath
if ($LASTEXITCODE -ne 0) {
  throw "Template fingerprint validation failed before generation: $TemplatePath"
}

if ([string]$ManifestData.anchor_mode -eq 'excel_named_range') {
  # Full validation remains available through --named-range-runtime-preflight;
  # the COM generation boundary intentionally uses the raw-only variant.
  & $PythonCommand (Join-Path $PSScriptRoot 'validate_template.py') --named-range-runtime-raw --template $TemplatePath --manifest $ManifestPath
  if ($LASTEXITCODE -ne 0) {
    throw "Named-range raw runtime preflight failed before COM output creation: $TemplatePath"
  }
}

if (-not $SkipTemplateValidation) {
  & $PythonCommand (Join-Path $PSScriptRoot 'validate_template.py') --template $TemplatePath --manifest $ManifestPath
  if ($LASTEXITCODE -ne 0) {
    throw "Template validation failed: $TemplatePath"
  }
}

function Resolve-SourceFiles([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) {
    throw "SourcePath not found: $path. Provide a 课程成绩单.xls file or a folder containing it."
  }
  $item = Get-Item -LiteralPath $path
  if ($item.PSIsContainer) {
    $candidate = Join-Path $item.FullName '课程成绩单.xls'
    if (-not (Test-Path -LiteralPath $candidate)) {
      throw "Folder does not contain 课程成绩单.xls: $($item.FullName)"
    }
    return @((Get-Item -LiteralPath $candidate))
  }
  return @($item)
}

function Normalize-Path([string]$path) {
  return [System.IO.Path]::GetFullPath($path)
}

function Path-Key([string]$path) {
  return (Normalize-Path $path).ToLowerInvariant()
}

function Assert-OutputPathsSafe($sourceItems, [string]$directory, [string[]]$finalPaths, [string[]]$qaPaths) {
  $outputKey = Path-Key $directory
  if ((Test-Path -LiteralPath $directory) -and -not (Test-Path -LiteralPath $directory -PathType Container)) {
    throw "Output directory is not a directory: $directory"
  }
  $skillDir = Split-Path -Parent $PSScriptRoot
  $packageDirs = @(
    (Join-Path $skillDir 'assets\templates\course-gradebook\v1.0.0'),
    (Join-Path $skillDir 'assets\templates\course-gradebook\v1.1.0'),
    (Join-Path $skillDir 'assets\平时成绩记分册模板.xls' | Split-Path -Parent)
  ) | ForEach-Object { Normalize-Path $_ }
  foreach ($packageDir in $packageDirs) {
    $packageKey = (Path-Key $packageDir).TrimEnd('\')
    if ($outputKey -eq $packageKey -or $outputKey.StartsWith($packageKey + '\')) {
      throw "Output directory must not be inside a template package directory: $directory"
    }
  }
  $forbidden = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($source in $sourceItems) { $null = $forbidden.Add((Path-Key $source.FullName)) }
  foreach ($path in @(
      $TemplatePath,
      $ManifestPath,
      $SchemaPath,
      (Join-Path $skillDir 'assets\templates\course-gradebook\v1.0.0\template.xls'),
      (Join-Path $skillDir 'assets\templates\course-gradebook\v1.1.0\template.xls'),
      (Join-Path $skillDir 'assets\平时成绩记分册模板.xls')
    )) {
    $null = $forbidden.Add((Path-Key $path))
  }
  $finalKeys = @()
  foreach ($finalPath in $finalPaths) {
    $target = Normalize-Path $finalPath
    $directoryKey = (Path-Key $directory).TrimEnd('\')
    $targetKey = Path-Key $target
    if (-not $targetKey.StartsWith($directoryKey + '\')) {
      throw "Output file must be inside OutputDir: $target"
    }
    if ((Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $target -PathType Container)) {
      throw "Output file path is a directory: $target"
    }
    if ([System.IO.Path]::GetExtension($target).ToLowerInvariant() -ne '.xls') {
      throw "Output file must use the .xls extension: $target"
    }
    if ($forbidden.Contains((Path-Key $target))) {
      if ($sourceItems.FullName -contains $target) {
        throw 'Output file must not overwrite the source workbook.'
      }
      if ((Path-Key $TemplatePath) -eq (Path-Key $target)) {
        throw 'Output file must not overwrite the template file.'
      }
      throw 'Output file must not overwrite an input or template package file.'
    }
    if ($finalKeys -contains $targetKey) {
      throw "Output file paths must be unique: $target"
    }
    $finalKeys += $targetKey
  }
  $qaKeys = @()
  foreach ($qaPath in $qaPaths) {
    if (-not $qaPath) { continue }
    $qaKey = Path-Key $qaPath
    if ($finalKeys -contains $qaKey) {
      throw 'QA report must not overwrite a generated XLS output.'
    }
    if ($qaKeys -contains $qaKey) {
      throw "QA report paths must be unique: $qaPath"
    }
    if ((Test-Path -LiteralPath $qaPath) -and (Test-Path -LiteralPath $qaPath -PathType Container)) {
      throw "QA report path is a directory: $qaPath"
    }
    if ($forbidden.Contains($qaKey)) {
      throw 'QA report must not overwrite an input or template package file.'
    }
    $qaKeys += $qaKey
  }
}

$RunTemporaryFiles = New-Object System.Collections.Generic.List[string]

function Track-RunTemporary([string]$path) {
  if ($path) { $RunTemporaryFiles.Add((Normalize-Path $path)) }
  return $path
}

function Remove-RunTemporaryFiles() {
  foreach ($path in @($RunTemporaryFiles | Sort-Object Length -Descending)) {
    if (Test-Path -LiteralPath $path) {
      Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
  $RunTemporaryFiles.Clear()
}

function Move-AtomicFile([string]$staged, [string]$destination) {
  if (Test-Path -LiteralPath $destination -PathType Leaf) {
    [System.IO.File]::Replace($staged, $destination, $null, $true)
  } else {
    [System.IO.File]::Move($staged, $destination)
  }
}

function Commit-OutputAndQaAtomically(
  [string]$candidate,
  [string]$finalPath,
  [string]$qaCandidate,
  [string]$qaPath
) {
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Output candidate does not exist: $candidate" }
  if (-not (Test-Path -LiteralPath $qaCandidate -PathType Leaf)) { throw "QA candidate does not exist: $qaCandidate" }
  $finalParent = Split-Path -Parent $finalPath
  $qaParent = Split-Path -Parent $qaPath
  New-Item -ItemType Directory -Path $finalParent -Force | Out-Null
  New-Item -ItemType Directory -Path $qaParent -Force | Out-Null
  $token = [guid]::NewGuid().ToString('N')
  $stagedXls = Join-Path $finalParent ('.' + (Split-Path -Leaf $finalPath) + '.' + $token + '.tmp')
  $stagedQa = Join-Path $qaParent ('.' + (Split-Path -Leaf $qaPath) + '.' + $token + '.tmp')
  $backupXls = Join-Path $finalParent ('.' + (Split-Path -Leaf $finalPath) + '.' + $token + '.bak')
  $backupQa = Join-Path $qaParent ('.' + (Split-Path -Leaf $qaPath) + '.' + $token + '.bak')
  $oldXls = Test-Path -LiteralPath $finalPath -PathType Leaf
  $oldQa = Test-Path -LiteralPath $qaPath -PathType Leaf
  $replacedXls = $false
  $replacedQa = $false
  try {
    Copy-Item -LiteralPath $candidate -Destination $stagedXls -Force
    Copy-Item -LiteralPath $qaCandidate -Destination $stagedQa -Force
    if ($oldXls) { Copy-Item -LiteralPath $finalPath -Destination $backupXls -Force }
    if ($oldQa) { Copy-Item -LiteralPath $qaPath -Destination $backupQa -Force }
    Move-AtomicFile $stagedXls $finalPath
    $replacedXls = $true
    Move-AtomicFile $stagedQa $qaPath
    $replacedQa = $true
  } catch {
    if ($replacedXls) {
      if ($oldXls) { Copy-Item -LiteralPath $backupXls -Destination $finalPath -Force }
      elseif (Test-Path -LiteralPath $finalPath) { Remove-Item -LiteralPath $finalPath -Force -ErrorAction SilentlyContinue }
    }
    if ($replacedQa) {
      if ($oldQa) { Copy-Item -LiteralPath $backupQa -Destination $qaPath -Force }
      elseif (Test-Path -LiteralPath $qaPath) { Remove-Item -LiteralPath $qaPath -Force -ErrorAction SilentlyContinue }
    }
    throw
  } finally {
    foreach ($path in @($stagedXls, $stagedQa, $backupXls, $backupQa)) {
      if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
    }
  }
}

function To-Number($value) {
  if ($null -eq $value -or $value -eq '') { return $null }
  return [double]$value
}

function Read-Meta($sheet) {
  $line2 = [string]$sheet.Range([string]$ManifestData.structure.source.metadata_line2_cell).Value2
  $line3 = [string]$sheet.Range([string]$ManifestData.structure.source.metadata_line3_cell).Value2
  $courseName = ''
  $teacher = ''
  $className = ''
  $term = ''
  $skillPct = 0.0
  $theoryPct = 0.0
  $regularPct = 0.0
  if ($line2 -match '课程名称:([^\r\n]+?)\s+教师:') { $courseName = $Matches[1].Trim() }
  if (-not $courseName -and $line2 -match '课程名称:([^\r\n ]+)') { $courseName = $Matches[1].Trim() }
  if ($line2 -match '教师:([^\r\n]+?)(?:\s*上课班级:|$)') { $teacher = $Matches[1].Trim() }
  if ($line2 -match '上课班级:([^\r\n]+?)(?:\s*成绩项目比例:|$)') { $className = $Matches[1].Trim() }
  if ($line3 -match '开课学期:([^\s]+)') { $term = $Matches[1].Trim() }
  if ($line2 -match '技能成绩(\d+(?:\.\d+)?)%') { $skillPct = [double]$Matches[1] / 100.0 }
  if ($line2 -match '理论成绩(\d+(?:\.\d+)?)%') { $theoryPct = [double]$Matches[1] / 100.0 }
  if ($line2 -match '平时成绩(\d+(?:\.\d+)?)%') { $regularPct = [double]$Matches[1] / 100.0 }
  [pscustomobject]@{
    CourseName = $courseName
    Teacher = $teacher
    ClassName = $className
    Term = $term
    SkillPct = $skillPct
    TheoryPct = $theoryPct
    RegularPct = $regularPct
  }
}

function HeaderMap($sheet, [int]$startCol, [int]$endCol, [int]$headerRow) {
  $map = @{}
  for ($c = $startCol; $c -le $endCol; $c++) {
    $h = ([string]$sheet.Cells.Item($headerRow, $c).Text).Trim()
    if ($h) { $map[$h] = $c }
  }
  return $map
}

function Read-Students($sheet) {
  $headerRow = [int]$ManifestData.structure.source.header_row
  $dataStartRow = [int]$ManifestData.structure.source.data_start_row
  $sourceHeaders = $ManifestData.structure.source.headers
  $studentIdHeader = [string]$sourceHeaders.student_id
  $studentNameHeader = [string]$sourceHeaders.student_name
  $regularHeader = [string]$sourceHeaders.regular
  $theoryHeader = [string]$sourceHeaders.theory
  $skillHeader = [string]$sourceHeaders.skill
  $totalHeader = [string]$sourceHeaders.total
  $used = $sheet.UsedRange
  $rows = $used.Row + $used.Rows.Count - 1
  $firstCol = $used.Column
  $cols = $used.Column + $used.Columns.Count - 1
  $starts = @()
  for ($c = $firstCol; $c -le $cols; $c++) {
    if ((([string]$sheet.Cells.Item($headerRow, $c).Text).Trim() -eq $studentIdHeader) -and
        (([string]$sheet.Cells.Item($headerRow, $c + 1).Text).Trim() -eq $studentNameHeader)) {
      $starts += $c
    }
  }
  if ($starts.Count -eq 0) {
    throw "Could not find 学号/姓名 headers in source workbook."
  }

  $blocks = @()
  for ($i = 0; $i -lt $starts.Count; $i++) {
    $start = [int]$starts[$i]
    $end = if ($i + 1 -lt $starts.Count) { [int]$starts[$i + 1] - 1 } else { $cols }
    $blocks += [pscustomobject]@{ Start = $start; Map = (HeaderMap $sheet $start $end $headerRow) }
  }

  $students = New-Object System.Collections.Generic.List[object]
  for ($r = $dataStartRow; $r -le $rows; $r++) {
    foreach ($block in $blocks) {
      $start = [int]$block.Start
      $map = $block.Map
      $id = ([string]$sheet.Cells.Item($r, $start).Text).Trim()
      $name = ([string]$sheet.Cells.Item($r, $start + 1).Text).Trim()
      if ($id -notmatch '^\d{8,}$' -or -not $name) { continue }
      if (-not $map.ContainsKey($theoryHeader) -or -not $map.ContainsKey($regularHeader) -or -not $map.ContainsKey($totalHeader)) {
        throw "Source block is missing 理论成绩/平时成绩/总成绩 headers."
      }
      $students.Add([pscustomobject]@{
        Id = $id
        Name = $name
        Skill = if ($map.ContainsKey($skillHeader)) { To-Number $sheet.Cells.Item($r, $map[$skillHeader]).Value2 } else { 0.0 }
        Theory = To-Number $sheet.Cells.Item($r, $map[$theoryHeader]).Value2
        Regular = To-Number $sheet.Cells.Item($r, $map[$regularHeader]).Value2
        Total = To-Number $sheet.Cells.Item($r, $map[$totalHeader]).Value2
      })
    }
  }
  if ($students.Count -eq 0) {
    throw "No students parsed from source workbook."
  }
  return $students
}

function Excel-Round([decimal]$value) {
  return [int][decimal]::Round($value, 0, [System.MidpointRounding]::AwayFromZero)
}

function Format-Percentage-Label([double]$value) {
  return (([decimal]$value * [decimal]100).ToString('0.############', [System.Globalization.CultureInfo]::InvariantCulture))
}

function Source-Total-Matches([decimal]$sourceTotal, [int]$expectedTotal) {
  return [Math]::Abs($sourceTotal - [decimal]$expectedTotal) -le [decimal]0.000000001
}

function Assert-HalfPointRegularScores($students) {
  for ($i = 0; $i -lt $students.Count; $i++) {
    [decimal]$regular = $students[$i].Regular
    if (($regular % [decimal]0.5) -ne 0) {
      throw "students[$i].regular must use 0.5-point increments; received $regular."
    }
  }
}

function Expected-Total($student, $meta) {
  [decimal]$weighted = ([decimal]$student.Regular * [decimal]$meta.RegularPct) +
    ([decimal]$student.Theory * [decimal]$meta.TheoryPct) +
    ([decimal]$student.Skill * [decimal]$meta.SkillPct)
  return Excel-Round $weighted
}

function Assert-SourceTotals($students, $meta) {
  for ($i = 0; $i -lt $students.Count; $i++) {
    $expected = Expected-Total $students[$i] $meta
    [decimal]$actual = $students[$i].Total
    if (-not (Source-Total-Matches $actual $expected)) {
      throw "Source total mismatch at record $($i + 1): expected $expected after Excel ROUND(...,0), received $actual. The source total may include a manual adjustment or be inconsistent with the configured formula."
    }
  }
}

function Normalize-Number($value) {
  if ($null -eq $value) { return $null }
  return [double]$value
}

function Assert-NormalizedInput($normalizedInput) {
  $inputJsonPath = Join-Path ([System.IO.Path]::GetTempPath()) ("gradebook-input-preflight-" + [guid]::NewGuid().ToString('N') + '.json')
  try {
    $normalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $inputJsonPath -Encoding UTF8
    & $PythonCommand (Join-Path $PSScriptRoot 'validate_input.py') --input-json $inputJsonPath --schema $SchemaPath
    if ($LASTEXITCODE -ne 0) {
      throw 'Input schema validation failed before output creation.'
    }
  } finally {
    Remove-Item -LiteralPath $inputJsonPath -Force -ErrorAction SilentlyContinue
  }
}

function Get-StableSeed([string]$text) {
  $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
  return [System.BitConverter]::ToInt32($hash, 0) -band 0x7fffffff
}

function Generate-RegularScores([double]$target, [string]$seedText, [int]$itemCount = 8) {
  if ($itemCount -le 0) { throw 'Manifest validation.regular_item_count must be positive.' }
  $targetUnits = [int][Math]::Round($target * 2)
  $targetTotalUnits = $targetUnits * $itemCount
  $rand = [System.Random]::new((Get-StableSeed $seedText))
  for ($attempt = 0; $attempt -lt 2000; $attempt++) {
    $scores = New-Object System.Collections.Generic.List[int]
    $sum = 0
    for ($i = 0; $i -lt ($itemCount - 1); $i++) {
      $low = [Math]::Max(-8, -1 * $targetUnits)
      $high = [Math]::Min(8, 200 - $targetUnits)
      $score = $targetUnits + $rand.Next($low, $high + 1)
      $scores.Add($score)
      $sum += $score
    }
    $last = $targetTotalUnits - $sum
    if ($last -lt 0 -or $last -gt 200) { continue }
    if ([Math]::Abs($last - $targetUnits) -gt 12) { continue }
    $scores.Add($last)
    $values = @($scores | ForEach-Object { $_ / 2.0 })
    $maxDev = ($values | ForEach-Object { [Math]::Abs($_ - $target) } | Measure-Object -Maximum).Maximum
    if ($maxDev -le 6.0) { return $values }
  }
  return @(1..$itemCount | ForEach-Object { $target })
}

function FormulaNumber([double]$n) {
  return $n.ToString('0.########', [System.Globalization.CultureInfo]::InvariantCulture)
}

function CellAddress([int]$row, [int]$col) {
  $name = ''
  $n = $col
  while ($n -gt 0) {
    $rem = ($n - 1) % 26
    $name = [char](65 + $rem) + $name
    $n = [Math]::Floor(($n - 1) / 26)
  }
  return "$name$row"
}

function ColumnToNumber([string]$column) {
  $value = 0
  foreach ($char in $column.ToUpperInvariant().ToCharArray()) {
    if ($char -lt 'A' -or $char -gt 'Z') { throw "Invalid Excel column: $column" }
    $value = $value * 26 + ([int][char]$char - [int][char]'A' + 1)
  }
  return $value
}

function ColumnLetter([int]$column) {
  if ($column -le 0) { throw "Invalid Excel column number: $column" }
  $name = ''
  $n = $column
  while ($n -gt 0) {
    $rem = ($n - 1) % 26
    $name = [char](65 + $rem) + $name
    $n = [Math]::Floor(($n - 1) / 26)
  }
  return $name
}

function Get-ManagedNameObject($workbook, [string]$name) {
  try {
    return $workbook.Names.Item($name)
  } catch {
    throw "Missing workbook-level managed name: $name"
  }
}

function Get-ManagedRangeLocation($workbook, [string]$name) {
  $nameObject = Get-ManagedNameObject $workbook $name
  if ([bool]$nameObject.Visible -eq $false) {
    throw "Managed name must be visible: $name"
  }
  $refersTo = [string]$nameObject.RefersTo
  if (-not $refersTo -or $refersTo.Contains('#REF!') -or $refersTo.Contains('[') -or $refersTo.Contains(',')) {
    throw "Managed name has a broken or non-contiguous reference: $name"
  }
  try {
    $range = $nameObject.RefersToRange
  } catch {
    throw "Managed name does not refer to a worksheet range: $name"
  }
  if ($null -eq $range -or [int]$range.Areas.Count -ne 1) {
    throw "Managed name must refer to one worksheet rectangle: $name"
  }
  if ([string]$range.Parent.Name -ne [string]$workbook.Worksheets.Item([string]$range.Parent.Name).Name) {
    throw "Managed name targets an invalid worksheet: $name"
  }
  return [pscustomobject]@{
    Name = $name
    Sheet = [string]$range.Parent.Name
    MinRow = [int]$range.Row
    MinCol = [int]$range.Column
    MaxRow = [int]$range.Row + [int]$range.Rows.Count - 1
    MaxCol = [int]$range.Column + [int]$range.Columns.Count - 1
  }
}

function Get-ManagedRange($workbook, [string]$name) {
  $nameObject = Get-ManagedNameObject $workbook $name
  try {
    $range = $nameObject.RefersToRange
  } catch {
    throw "Managed name does not refer to a worksheet range: $name"
  }
  if ($null -eq $range -or [int]$range.Areas.Count -ne 1) {
    throw "Managed name must refer to one worksheet rectangle: $name"
  }
  return ,$range
}

function Set-ManagedCellValue($ranges, [string]$name, $value) {
  $range = $ranges[[string]$name]
  if ($null -eq $range -or [int]$range.Cells.Count -ne 1) {
    throw "Managed name must target one cell for a scalar write: $name"
  }
  try {
    if ($value -is [string]) { $null = $range.Value2 = [string]$value } else { $null = $range.Value = $value }
  } catch { throw "Named scalar write failed for $name (value type $($value.GetType().FullName)): $($_.Exception.Message)" }
}

function Set-ManagedOffsetValue($ranges, [string]$name, [int]$rowOffset, [int]$colOffset, $value) {
  $range = $ranges[[string]$name]
  if ($null -eq $range) { throw "Missing managed write range: $name" }
  if ($rowOffset -lt 0 -or $colOffset -lt 0) {
    throw "Named value write offset must be non-negative for ${name}: requested row=$rowOffset, col=$colOffset"
  }
  $rowCount = [int]$range.Rows.Count
  $colCount = [int]$range.Columns.Count
  if ($rowOffset -ge $rowCount -or $colOffset -ge $colCount) {
    throw "Named value write offset out of bounds for ${name}: requested row=$rowOffset, col=$colOffset, range rows=$rowCount, cols=$colCount"
  }
  $cell = $range.Cells.Item($rowOffset + 1, $colOffset + 1)
  try {
    if ($value -is [string]) { $null = $cell.Value2 = [string]$value } else { $null = $cell.Value = $value }
  } catch { throw "Named value write failed for $name at offset $rowOffset,$colOffset (value type $($value.GetType().FullName)): $($_.Exception.Message)" }
}

function Set-ManagedOffsetFormula($ranges, [string]$name, [int]$rowOffset, [int]$colOffset, [string]$formula) {
  $range = $ranges[[string]$name]
  if ($null -eq $range) { throw "Missing managed formula range: $name" }
  if ($rowOffset -lt 0 -or $colOffset -lt 0) {
    throw "Named formula write offset must be non-negative for ${name}: requested row=$rowOffset, col=$colOffset"
  }
  $rowCount = [int]$range.Rows.Count
  $colCount = [int]$range.Columns.Count
  if ($rowOffset -ge $rowCount -or $colOffset -ge $colCount) {
    throw "Named formula write offset out of bounds for ${name}: requested row=$rowOffset, col=$colOffset, range rows=$rowCount, cols=$colCount"
  }
  $cell = $range.Cells.Item($rowOffset + 1, $colOffset + 1)
  try { $null = $cell.Formula = $formula } catch { throw "Named formula write failed for $name at offset $rowOffset,${colOffset}: $($_.Exception.Message)" }
}

function Get-ManagedRanges($workbook, [string]$variant) {
  $required = if ($variant -eq 'with_skill') {
    @($ManifestData.anchors.variants.with_skill.required)
  } else {
    @($ManifestData.anchors.variants.without_skill.required)
  }
  $locations = @{}
  foreach ($name in $required) {
    $locations[[string]$name] = Get-ManagedRangeLocation $workbook ([string]$name)
  }
  $forbidden = if ($variant -eq 'with_skill') {
    @($ManifestData.anchors.variants.with_skill.forbidden)
  } else {
    @($ManifestData.anchors.variants.without_skill.forbidden)
  }
  foreach ($name in $forbidden) {
    try {
      $null = $workbook.Names.Item([string]$name)
      throw "Forbidden managed name still exists for $variant variant: $name"
    } catch [System.Runtime.InteropServices.COMException] {
      # A missing forbidden name is the expected variant state.
    }
  }
  return $locations
}

function Assert-ManagedRuntimeContract($workbook, [string]$variant, $locations) {
  $required = if ($variant -eq 'with_skill') {
    @($ManifestData.anchors.variants.with_skill.required)
  } else {
    @($ManifestData.anchors.variants.without_skill.required)
  }
  $seen = @{}
  foreach ($name in $required) {
    $location = $locations[[string]$name]
    if ($null -eq $location) { throw "Missing runtime managed location: $name" }
    $physicalKey = "{0}|{1}|{2}|{3}|{4}" -f $location.Sheet, $location.MinRow, $location.MinCol, $location.MaxRow, $location.MaxCol
    if ($seen.ContainsKey($physicalKey)) {
      throw "Managed named ranges share one physical destination at ${physicalKey}: $($seen[$physicalKey]), $name"
    }
    $seen[$physicalKey] = [string]$name
  }
  $table = $locations['gb_data_table']
  $templateRow = $locations['gb_template_row']
  if ($null -eq $table -or $null -eq $templateRow) { throw 'Runtime managed contract is missing the data table or template row' }
  if ($templateRow.MinRow -ne $table.MinRow -or $templateRow.MinCol -ne $table.MinCol -or $templateRow.MaxCol -ne $table.MaxCol) {
    throw 'gb_template_row must equal the first row of gb_data_table at runtime'
  }
  $regular = $locations['gb_regular_items']
  if ($null -eq $regular -or ($regular.MaxCol - $regular.MinCol + 1) -ne 8) {
    throw 'gb_regular_items must contain exactly 8 columns at runtime'
  }
  $dataNames = @(
    'gb_serial_col', 'gb_student_id_col', 'gb_student_name_col', 'gb_regular_items',
    'gb_regular_weighted_col', 'gb_theory_score_col', 'gb_theory_weighted_col', 'gb_total_score_col'
  )
  if ($variant -eq 'with_skill') { $dataNames += @('gb_skill_score_col', 'gb_skill_weighted_col') }
  foreach ($name in $dataNames) {
    $location = $locations[[string]$name]
    if ($null -eq $location) { throw "Runtime managed contract is missing data range: $name" }
    if ($location.MinRow -ne $table.MinRow -or $location.MaxRow -ne $table.MaxRow) {
      throw "$name must use the same data rows as gb_data_table at runtime"
    }
    if ($location.MinCol -lt $table.MinCol -or $location.MaxCol -gt $table.MaxCol) {
      throw "$name must be contained in gb_data_table at runtime"
    }
  }
  if ($regular.MaxCol + 1 -ne $locations['gb_regular_weighted_col'].MinCol) {
    throw 'gb_regular_items must be immediately before gb_regular_weighted_col at runtime'
  }
}

function Set-ManagedWorkbookName($workbook, [string]$name, $location) {
  try {
    $workbook.Names.Item($name).Delete()
  } catch {
    # The name may not exist yet.
  }
  $sheet = $workbook.Worksheets.Item([string]$location.Sheet)
  $first = $sheet.Cells.Item([int]$location.MinRow, [int]$location.MinCol).Address($true, $true)
  $last = $sheet.Cells.Item([int]$location.MaxRow, [int]$location.MaxCol).Address($true, $true)
  $refersTo = "='$($location.Sheet)'!$first"
  if ($first -ne $last) { $refersTo = "='$($location.Sheet)'!$first`:$last" }
  $null = $workbook.Names.Add($name, $refersTo)
}

function Shift-ManagedLocationAfterDelete($location, [int]$startCol, [int]$count) {
  $endCol = $startCol + $count - 1
  if ($location.MaxCol -lt $startCol) { return $location }
  if ($location.MinCol -gt $endCol) {
    $location.MinCol -= $count
    $location.MaxCol -= $count
    return $location
  }
  if ($location.MinCol -ge $startCol -and $location.MaxCol -le $endCol) {
    $location.MinCol = $startCol
    $location.MaxCol = $startCol
    return $location
  }
  if ($location.MinCol -lt $startCol -and $location.MaxCol -gt $endCol) {
    $location.MaxCol -= $count
    return $location
  }
  if ($location.MinCol -lt $startCol -and $location.MaxCol -le $endCol) {
    $location.MaxCol = $startCol - 1
    return $location
  }
  if ($location.MinCol -ge $startCol -and $location.MaxCol -gt $endCol) {
    $location.MinCol = $startCol
    $location.MaxCol -= $count
    return $location
  }
  throw "Could not shift managed name $($location.Name) after deleting columns."
}

function Rebuild-ManagedNamesAfterColumnDelete($workbook, $original, [int]$startCol, [int]$count) {
  $required = @($ManifestData.anchors.variants.without_skill.required)
  $removed = @($ManifestData.anchors.variants.without_skill.forbidden)
  foreach ($name in $removed) {
    try { $workbook.Names.Item([string]$name).Delete() } catch { }
  }
  foreach ($name in $required) {
    $location = $original[[string]$name]
    if ($null -eq $location) { throw "Missing pre-delete location for managed name: $name" }
    $shifted = Shift-ManagedLocationAfterDelete $location $startCol $count
    Set-ManagedWorkbookName $workbook ([string]$name) $shifted
  }
}

function Update-ManagedNamesForCapacity($workbook, $ranges, [int]$lastRow) {
  $dataNames = @(
    'gb_data_table', 'gb_serial_col', 'gb_student_id_col', 'gb_student_name_col',
    'gb_regular_items', 'gb_regular_weighted_col', 'gb_theory_score_col',
    'gb_theory_weighted_col', 'gb_skill_score_col', 'gb_skill_weighted_col',
    'gb_total_score_col'
  )
  $allNames = @(
    $ManifestData.anchors.variants.with_skill.required
    $ManifestData.anchors.variants.without_skill.required
  ) | ForEach-Object { [string]$_ } | Select-Object -Unique
  foreach ($name in $allNames) {
    if (-not $ranges.ContainsKey([string]$name)) { continue }
    $location = $ranges[[string]$name]
    if ($dataNames -contains [string]$name) { $location.MaxRow = $lastRow }
    Set-ManagedWorkbookName $workbook ([string]$name) $location
  }
}

function Build-One-NamedRange($excel, [string]$candidatePath, [string]$finalPath, [string]$sourceFile, $meta, $students, $normalizedInput) {
  Copy-Item -LiteralPath $TemplatePath -Destination $candidatePath -Force
  $wb = $excel.Workbooks.Open($candidatePath)
  $buildSucceeded = $false
  try {
    $wb.CheckCompatibility = $false
    $hasSkill = $meta.SkillPct -gt 0.000001
    $variant = if ($hasSkill) { 'with_skill' } else { 'without_skill' }
    $original = Get-ManagedRanges $wb 'with_skill'
    Assert-ManagedRuntimeContract $wb 'with_skill' $original
    $ws = $wb.Worksheets.Item([string]$original['gb_data_table'].Sheet)
    if (-not $hasSkill) {
      $skillStart = [int]$original['gb_skill_score_col'].MinCol
      $skillRange = "$(ColumnLetter $skillStart):$(ColumnLetter ($skillStart + 1))"
      $null = $ws.Range($skillRange).EntireColumn.Delete()
      Rebuild-ManagedNamesAfterColumnDelete $wb $original $skillStart 2
    }
    $ranges = Get-ManagedRanges $wb $variant
    Assert-ManagedRuntimeContract $wb $variant $ranges
    $table = $ranges['gb_data_table']
    $dataStart = [int]$table.MinRow
    $templateLastDataRow = [int]$table.MaxRow
    $styleSourceRow = [int]$ranges['gb_template_row'].MinRow
    if ($students.Count -gt ($templateLastDataRow - $dataStart + 1)) {
      $needed = $students.Count - ($templateLastDataRow - $dataStart + 1)
      for ($i = 0; $i -lt $needed; $i++) {
        $insertAt = $templateLastDataRow + 1
        $null = $ws.Rows.Item($styleSourceRow).Copy()
        $null = $ws.Rows.Item($insertAt).Insert(-4121)
        $templateLastDataRow++
      }
      Update-ManagedNamesForCapacity $wb $ranges $templateLastDataRow
      $ranges = Get-ManagedRanges $wb $variant
      Assert-ManagedRuntimeContract $wb $variant $ranges
      $table = $ranges['gb_data_table']
    }

    $tableRange = $ws.Range(
      (CellAddress ([int]$table.MinRow) ([int]$table.MinCol)),
      (CellAddress ([int]$table.MaxRow) ([int]$table.MaxCol))
    )
    $writeRanges = @{}
    $writeNames = if ($hasSkill) {
      @($ManifestData.anchors.variants.with_skill.required)
    } else {
      @($ManifestData.anchors.variants.without_skill.required)
    }
    foreach ($name in $writeNames) {
      $writeRanges[[string]$name] = Get-ManagedRange $wb ([string]$name)
    }
    if ($null -eq $writeRanges['gb_data_table']) { throw 'Missing managed write range: gb_data_table' }
    $writeRanges['gb_data_table'].ClearContents()
    Set-ManagedCellValue $writeRanges 'gb_term' $meta.Term
    Set-ManagedCellValue $writeRanges 'gb_course' $meta.CourseName
    Set-ManagedCellValue $writeRanges 'gb_teacher' $meta.Teacher
    Set-ManagedCellValue $writeRanges 'gb_class_name' $meta.ClassName
    Set-ManagedCellValue $writeRanges 'gb_header_regular' ('平时成绩({0}%)' -f (Format-Percentage-Label $meta.RegularPct))
    Set-ManagedCellValue $writeRanges 'gb_header_theory' ('理论成绩({0}%)' -f (Format-Percentage-Label $meta.TheoryPct))
    if ($hasSkill) {
      Set-ManagedCellValue $writeRanges 'gb_header_skill' ('技能成绩（{0}%）' -f (Format-Percentage-Label $meta.SkillPct))
    } else {
      # Excel's native width is converted to a slightly larger LibreOffice width;
      # 17.45 round-trips to the same protected width as the Python path's 18.
      $null = $ws.Columns.Item((ColumnLetter ([int]$ranges['gb_total_score_col'].MinCol))).ColumnWidth = 17.45
    }

    $serialCol = [int]$ranges['gb_serial_col'].MinCol
    $studentIdCol = [int]$ranges['gb_student_id_col'].MinCol
    $studentNameCol = [int]$ranges['gb_student_name_col'].MinCol
    $regularStartCol = [int]$ranges['gb_regular_items'].MinCol
    $regularEndCol = [int]$ranges['gb_regular_items'].MaxCol
    $regularWeightedCol = [int]$ranges['gb_regular_weighted_col'].MinCol
    $theoryScoreCol = [int]$ranges['gb_theory_score_col'].MinCol
    $theoryWeightedCol = [int]$ranges['gb_theory_weighted_col'].MinCol
    $skillScoreCol = if ($hasSkill) { [int]$ranges['gb_skill_score_col'].MinCol } else { 0 }
    $skillWeightedCol = if ($hasSkill) { [int]$ranges['gb_skill_weighted_col'].MinCol } else { 0 }
    $totalCol = [int]$ranges['gb_total_score_col'].MinCol
    $regularStartLetter = ColumnLetter $regularStartCol
    $regularEndLetter = ColumnLetter $regularEndCol
    $theoryScoreLetter = ColumnLetter $theoryScoreCol
    $skillScoreLetter = if ($hasSkill) { ColumnLetter $skillScoreCol } else { '' }
    $regularPct = FormulaNumber $meta.RegularPct
    $theoryPct = FormulaNumber $meta.TheoryPct
    $skillPct = FormulaNumber $meta.SkillPct
    $classCode = Split-Path -Leaf (Split-Path -Parent $sourceFile)
    for ($i = 0; $i -lt $students.Count; $i++) {
      $student = $students[$i]
      $r = $dataStart + $i
      $scores = Generate-RegularScores $student.Regular ("$classCode|$($student.Id)|$($student.Regular)") ([int]$ManifestData.validation.regular_item_count)
      Set-ManagedOffsetValue $writeRanges 'gb_serial_col' $i 0 ([double]($i + 1))
      Set-ManagedOffsetValue $writeRanges 'gb_student_id_col' $i 0 $student.Id
      $null = $writeRanges['gb_student_id_col'].Cells.Item($i + 1, 1).NumberFormatLocal = '@'
      Set-ManagedOffsetValue $writeRanges 'gb_student_name_col' $i 0 $student.Name
      for ($j = 0; $j -lt $scores.Count; $j++) {
        Set-ManagedOffsetValue $writeRanges 'gb_regular_items' $i $j ([double]$scores[$j])
      }
      Set-ManagedOffsetFormula $writeRanges 'gb_regular_weighted_col' $i 0 ("=AVERAGE({0}{1}:{2}{1})*{3}" -f $regularStartLetter, $r, $regularEndLetter, $regularPct)
      Set-ManagedOffsetValue $writeRanges 'gb_theory_score_col' $i 0 ([System.Convert]::ToDouble($student.Theory))
      Set-ManagedOffsetFormula $writeRanges 'gb_theory_weighted_col' $i 0 ("={0}{1}*{2}" -f $theoryScoreLetter, $r, $theoryPct)
      if ($hasSkill) {
        Set-ManagedOffsetValue $writeRanges 'gb_skill_score_col' $i 0 ([System.Convert]::ToDouble($student.Skill))
        Set-ManagedOffsetFormula $writeRanges 'gb_skill_weighted_col' $i 0 ("={0}{1}*{2}" -f $skillScoreLetter, $r, $skillPct)
        Set-ManagedOffsetFormula $writeRanges 'gb_total_score_col' $i 0 ("=ROUND(AVERAGE({0}{1}:{2}{1})*{3}+{4}{1}*{5}+{6}{1}*{7},0)" -f $regularStartLetter, $r, $regularEndLetter, $regularPct, $theoryScoreLetter, $theoryPct, $skillScoreLetter, $skillPct)
      } else {
        Set-ManagedOffsetFormula $writeRanges 'gb_total_score_col' $i 0 ("=ROUND(AVERAGE({0}{1}:{2}{1})*{3}+{4}{1}*{5},0)" -f $regularStartLetter, $r, $regularEndLetter, $regularPct, $theoryScoreLetter, $theoryPct)
      }
    }
    $wb.Application.CalculateFullRebuild()
    $wb.Save()
    $buildSucceeded = $true
  } finally {
    $wb.Close($buildSucceeded)
  }
  return [pscustomobject]@{
    Source = ''
    Output = $candidatePath
    FinalOutput = $finalPath
    Count = $students.Count
    Course = $meta.CourseName
    ClassName = $meta.ClassName
    HasSkill = $hasSkill
    NamedRangeVariant = $variant
    NamedRangeCapacityEnd = $templateLastDataRow
    RegularPct = $meta.RegularPct
    TheoryPct = $meta.TheoryPct
    SkillPct = $meta.SkillPct
    Engine = 'excel-com'
    NormalizedInput = $normalizedInput
  }
}

function Set-Value($sheet, [int]$row, [int]$col, $value) {
  $addr = CellAddress $row $col
  if ($value -is [string]) {
    $sheet.Range($addr).Value2 = [string]$value
  } else {
    $sheet.Range($addr).Value = $value
  }
}

function Set-Formula($sheet, [int]$row, [int]$col, [string]$formula) {
  $sheet.Range((CellAddress $row $col)).Formula = $formula
}

function Build-One($excel, [string]$sourceFile, [string]$candidatePath, [string]$finalPath) {
  $srcWb = $excel.Workbooks.Open($sourceFile, 0, $true)
  try {
    $srcSheet = $srcWb.Worksheets.Item(1)
    $meta = Read-Meta $srcSheet
    $students = @(Read-Students $srcSheet)
    Assert-HalfPointRegularScores $students
    Assert-SourceTotals $students $meta
    $normalizedStudents = @($students | ForEach-Object {
      [ordered]@{
        id = [string]$_.Id
        name = [string]$_.Name
        regular = Normalize-Number $_.Regular
        theory = Normalize-Number $_.Theory
        skill = Normalize-Number $_.Skill
        total = Normalize-Number $_.Total
      }
    })
    $normalizedInput = [ordered]@{
      term = [string]$meta.Term
      course = [string]$meta.CourseName
      teacher = [string]$meta.Teacher
      class_name = [string]$meta.ClassName
      weights = [ordered]@{
        regular = [double]$meta.RegularPct
        theory = [double]$meta.TheoryPct
        skill = [double]$meta.SkillPct
      }
      students = $normalizedStudents
    }
    Assert-NormalizedInput $normalizedInput
  } finally {
    $srcWb.Close($false)
  }

  $outPath = $candidatePath
  if ([string]$ManifestData.anchor_mode -eq 'excel_named_range') {
    $namedResult = @(Build-One-NamedRange $excel $candidatePath $finalPath $sourceFile $meta $students $normalizedInput)[-1]
    $namedResult.Source = $sourceFile
    return $namedResult
  }
  Copy-Item -LiteralPath $TemplatePath -Destination $outPath -Force

  $wb = $excel.Workbooks.Open($outPath)
  $buildSucceeded = $false
  try {
    $wb.CheckCompatibility = $false
    $structure = $ManifestData.structure
    $columns = $structure.columns
    $ws = $wb.Worksheets.Item([string]$structure.worksheet)
    $hasSkill = $meta.SkillPct -gt 0.000001
    $skillStartCol = ColumnToNumber ([string]$columns.skill_score)
    $skillWeightedCol = ColumnToNumber ([string]$columns.skill_weighted)
    $legacyMetadataVerticalBorder = $null
    if (-not $hasSkill) {
      $sourceBorder = $ws.Range("$($columns.theory_weighted)2").Borders.Item(10)
      $legacyMetadataVerticalBorder = [ordered]@{
        LineStyle = $sourceBorder.LineStyle
        Weight = $sourceBorder.Weight
        Color = $sourceBorder.Color
      }
      $null = $ws.Range("$($columns.skill_score):$($columns.skill_weighted)").EntireColumn.Delete()
    }

    $dataStart = [int]$structure.data_start_row
    $templateLastDataRow = [int]$structure.template_last_data_row
    $styleSourceRow = [int]$structure.style_source_row
    $serialCol = ColumnToNumber ([string]$columns.serial)
    $studentIdCol = ColumnToNumber ([string]$columns.student_id)
    $studentNameCol = ColumnToNumber ([string]$columns.student_name)
    $regularStartCol = ColumnToNumber ([string]$columns.regular_items_start)
    $regularEndCol = ColumnToNumber ([string]$columns.regular_items_end)
    $regularItemCount = [int]$ManifestData.validation.regular_item_count
    if ($regularItemCount -le 0) { throw 'Manifest validation.regular_item_count must be positive.' }
    if (($regularEndCol - $regularStartCol + 1) -ne $regularItemCount) {
      throw 'Manifest regular item count does not match columns.regular_items_start/regular_items_end.'
    }
    $regularWeightedCol = ColumnToNumber ([string]$columns.regular_weighted)
    $theoryScoreCol = ColumnToNumber ([string]$columns.theory_score)
    $theoryWeightedCol = ColumnToNumber ([string]$columns.theory_weighted)
    $totalCol = if ($hasSkill) { ColumnToNumber ([string]$columns.total_score) } else { ColumnToNumber ([string]$structure.no_skill_total_column) }
    if ($students.Count -gt ($templateLastDataRow - $dataStart + 1)) {
      $needed = $students.Count - ($templateLastDataRow - $dataStart + 1)
      for ($i = 0; $i -lt $needed; $i++) {
        $insertAt = $templateLastDataRow + 1
        $null = $ws.Rows.Item($styleSourceRow).Copy()
        $ws.Rows.Item($insertAt).Insert(-4121)
        $templateLastDataRow++
      }
    }

    $lastCol = if ($hasSkill) { [string]$columns.total_score } else { [string]$structure.no_skill_total_column }
    $firstCol = [string]$columns.serial
    $ws.Range("${firstCol}${dataStart}:${lastCol}${templateLastDataRow}").ClearContents()
    $ws.Range([string]$structure.metadata.term).Value2 = $meta.Term
    $ws.Range([string]$structure.metadata.course).Value2 = $meta.CourseName
    $ws.Range([string]$structure.metadata.teacher).Value2 = $meta.Teacher
    $ws.Range([string]$structure.metadata.class_name).Value2 = $meta.ClassName
    $ws.Range([string]$structure.headers.regular).Value2 = ('平时成绩({0}%)' -f (Format-Percentage-Label $meta.RegularPct))
    $ws.Range([string]$structure.headers.theory).Value2 = ('理论成绩({0}%)' -f (Format-Percentage-Label $meta.TheoryPct))
    if ($hasSkill) {
      $ws.Range([string]$structure.headers.skill).Value2 = ('技能成绩（{0}%）' -f (Format-Percentage-Label $meta.SkillPct))
    } else {
      # 17.45 round-trips through LibreOffice to the protected width 18.0.
      $null = $ws.Columns.Item([string]$structure.no_skill_total_column).ColumnWidth = 17.45
      $verticalBorder = $ws.Range(
        "$($columns.theory_score)2:$($structure.no_skill_total_column)2"
      ).Borders.Item(11)
      $null = $verticalBorder.LineStyle = $legacyMetadataVerticalBorder.LineStyle
      $null = $verticalBorder.Weight = $legacyMetadataVerticalBorder.Weight
      $null = $verticalBorder.Color = $legacyMetadataVerticalBorder.Color
      $horizontalBorder = $ws.Range(
        "$($columns.theory_score)2:$($columns.theory_weighted)3"
      ).Borders.Item(12)
      $null = $horizontalBorder.LineStyle = $legacyMetadataVerticalBorder.LineStyle
      $null = $horizontalBorder.Weight = $legacyMetadataVerticalBorder.Weight
      $null = $horizontalBorder.Color = $legacyMetadataVerticalBorder.Color
    }

    $regularPct = FormulaNumber $meta.RegularPct
    $theoryPct = FormulaNumber $meta.TheoryPct
    $skillPct = FormulaNumber $meta.SkillPct

    for ($i = 0; $i -lt $students.Count; $i++) {
      $student = $students[$i]
      $r = $dataStart + $i
      $scores = Generate-RegularScores $student.Regular ("$classCode|$($student.Id)|$($student.Regular)") $regularItemCount
      Set-Value $ws $r $serialCol ([double]($i + 1))
      $ws.Range((CellAddress $r $studentIdCol)).NumberFormatLocal = '@'
      Set-Value $ws $r $studentIdCol $student.Id
      Set-Value $ws $r $studentNameCol $student.Name
      for ($j = 0; $j -lt $regularItemCount; $j++) {
        Set-Value $ws $r ($regularStartCol + $j) ([double]$scores[$j])
      }
      Set-Formula $ws $r $regularWeightedCol "=AVERAGE($($columns.regular_items_start)$r`:$($columns.regular_items_end)$r)*$regularPct"
      Set-Value $ws $r $theoryScoreCol ([System.Convert]::ToDouble($student.Theory))
      Set-Formula $ws $r $theoryWeightedCol "=$($columns.theory_score)$r*$theoryPct"
      if ($hasSkill) {
        Set-Value $ws $r $skillStartCol ([System.Convert]::ToDouble($student.Skill))
        Set-Formula $ws $r $skillWeightedCol "=$($columns.skill_score)$r*$skillPct"
        Set-Formula $ws $r $totalCol "=ROUND(AVERAGE($($columns.regular_items_start)$r`:$($columns.regular_items_end)$r)*$regularPct+$($columns.theory_score)$r*$theoryPct+$($columns.skill_score)$r*$skillPct,0)"
      } else {
        Set-Formula $ws $r $totalCol "=ROUND(AVERAGE($($columns.regular_items_start)$r`:$($columns.regular_items_end)$r)*$regularPct+$($columns.theory_score)$r*$theoryPct,0)"
      }
    }

    $firstExtraRow = $dataStart + $students.Count
    if ($firstExtraRow -le $templateLastDataRow) {
      $null = $ws.Range("${firstCol}${firstExtraRow}:${firstCol}${templateLastDataRow}").EntireRow.Delete()
    }
    $excel.CalculateFullRebuild()
    $wb.Save()
    $buildSucceeded = $true
  } finally {
    $wb.Close($buildSucceeded)
  }

  [pscustomobject]@{
    Source = $sourceFile
    Output = $candidatePath
    FinalOutput = $finalPath
    Count = $students.Count
    Course = $meta.CourseName
    ClassName = $meta.ClassName
    HasSkill = $hasSkill
    RegularPct = $meta.RegularPct
    TheoryPct = $meta.TheoryPct
    SkillPct = $meta.SkillPct
    Engine = 'excel-com'
    NormalizedInput = $normalizedInput
  }
}

$sources = Resolve-SourceFiles $SourcePath
if (-not $OutputDir) {
  $OutputDir = Join-Path (Split-Path -Parent $sources[0].FullName) '平时成绩记分册_生成'
}
if ($OutputFile) {
  if ($sources.Count -ne 1) {
    throw '-OutputFile can only be used when exactly one source workbook is selected.'
  }
  if (-not [System.IO.Path]::IsPathRooted($OutputFile)) {
    $OutputFile = Join-Path $OutputDir $OutputFile
  }
  $OutputFile = [System.IO.Path]::GetFullPath($OutputFile)
  $OutputDir = Split-Path -Parent $OutputFile
}
$finalPaths = @()
foreach ($source in $sources) {
  $classCode = Split-Path -Leaf (Split-Path -Parent $source.FullName)
  if (-not $classCode -or $classCode -eq '.') {
    $classCode = [System.IO.Path]::GetFileNameWithoutExtension($source.FullName)
  }
  $finalPaths += if ($OutputFile) { $OutputFile } else { Join-Path $OutputDir ("{0}-平时成绩记分册.xls" -f $classCode) }
}
$qaPaths = @()
foreach ($finalPath in $finalPaths) {
  if ($QaReportPath) { $qaPaths += $QaReportPath }
  elseif ($finalPaths.Count -eq 1) { $qaPaths += (Join-Path $OutputDir 'qa-report.json') }
  else { $qaPaths += (Join-Path $OutputDir (([System.IO.Path]::GetFileNameWithoutExtension($finalPath)) + '.qa-report.json')) }
}
Assert-OutputPathsSafe $sources $OutputDir $finalPaths $qaPaths
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$runRoot = Track-RunTemporary (Join-Path ([System.IO.Path]::GetTempPath()) ("gradebook-com-run-" + [guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$results = @()
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $excel.AskToUpdateLinks = $false
  try {
    for ($index = 0; $index -lt $sources.Count; $index++) {
      $source = $sources[$index]
      $candidateDir = Join-Path $runRoot ("candidate-{0}" -f $index)
      New-Item -ItemType Directory -Path $candidateDir -Force | Out-Null
      $candidatePath = Join-Path $candidateDir (([guid]::NewGuid().ToString('N')) + '-' + (Split-Path -Leaf $finalPaths[$index]))
      $built = @(Build-One $excel $source.FullName $candidatePath $finalPaths[$index])[-1]
      $results += $built
      $rawArgs = @(
        '--raw-runtime-preflight',
        '--output-dir', $candidateDir,
        '--output-file', $candidatePath,
        '--manifest', $ManifestPath,
        '--template-path', $TemplatePath,
        '--engine', 'excel-com'
      )
      if ($built.NamedRangeVariant) { $rawArgs += @('--variant', [string]$built.NamedRangeVariant) }
      & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @rawArgs
      if ($LASTEXITCODE -ne 0) { throw "Raw output runtime preflight failed: $candidatePath" }
    }
  } finally {
    $excel.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
  }

  $validationArgs = @(
    '--manifest', $ManifestPath,
    '--schema', $SchemaPath,
    '--template-path', $TemplatePath,
    '--engine', 'excel-com'
  )
  if ($TemplateWasProvided) { $validationArgs += '--custom-template' }
  if ($SkipTemplateValidation) { $validationArgs += '--skip-template-validation' }
  for ($index = 0; $index -lt $results.Count; $index++) {
    $result = $results[$index]
    $finalPath = [string]$finalPaths[$index]
    $validationDir = Join-Path $runRoot ("validation-{0}" -f $index)
    New-Item -ItemType Directory -Path $validationDir -Force | Out-Null
    $validationFile = Join-Path $validationDir (Split-Path -Leaf $finalPath)
    Copy-Item -LiteralPath $result.Output -Destination $validationFile -Force
    $normalizedJsonPath = Join-Path $validationDir 'normalized-input.json'
    $result.NormalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $normalizedJsonPath -Encoding UTF8
    $qaCandidate = Join-Path $validationDir 'qa-report.json'
    $runArgs = @('--input-json', $normalizedJsonPath, '--output-dir', $validationDir, '--output-file', $validationFile, '--qa-report', $qaCandidate) + $validationArgs
    if ($SkipOutputValidation) { $runArgs += '--skip-validation' }
    & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @runArgs
    if ($LASTEXITCODE -ne 0) {
      if ($SkipOutputValidation) { throw "Could not write skipped QA report: $($result.Output)" }
      throw "Output validation failed: $($result.Output)"
    }
    Commit-OutputAndQaAtomically $result.Output $finalPath $qaCandidate $qaPaths[$index]
    $result.Output = $finalPath
    $result.PSObject.Properties.Remove('FinalOutput')
    if ($SkipOutputValidation) { Write-Warning 'Output validation skipped; QA report status is skipped.' }
  }
} finally {
  Remove-RunTemporaryFiles
}

foreach ($result in $results) {
  $result.PSObject.Properties.Remove('NormalizedInput')
}
$results | ConvertTo-Json -Depth 4



