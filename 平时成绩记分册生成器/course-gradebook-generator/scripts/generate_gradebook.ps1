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

if (-not $ManifestPath) {
  $ManifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\templates\course-gradebook\v1.0.0\manifest.yaml'
}
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
& $PythonCommand $ManifestToJson --manifest $ManifestPath --output $ManifestJsonPath
if ($LASTEXITCODE -ne 0) {
  throw "Could not parse manifest: $ManifestPath"
}
$ManifestData = (Get-Content -LiteralPath $ManifestJsonPath -Raw -Encoding UTF8) | ConvertFrom-Json
Remove-Item -LiteralPath $ManifestJsonPath -Force -ErrorAction SilentlyContinue

$TemplateWasProvided = [bool]$TemplatePath
if (-not $TemplatePath) {
  $TemplatePath = Join-Path (Split-Path -Parent $ManifestPath) $ManifestData.template.file
}

if (-not (Test-Path -LiteralPath $TemplatePath)) {
  throw "Template not found: $TemplatePath"
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

function Build-One($excel, [string]$sourceFile, [string]$outputDirectory, [string]$outputFile = "") {
  $srcWb = $excel.Workbooks.Open($sourceFile, 0, $true)
  try {
    $srcSheet = $srcWb.Worksheets.Item(1)
    $meta = Read-Meta $srcSheet
    $students = @(Read-Students $srcSheet)
    Assert-HalfPointRegularScores $students
    Assert-SourceTotals $students $meta
  } finally {
    $srcWb.Close($false)
  }

  $classCode = Split-Path -Leaf (Split-Path -Parent $sourceFile)
  if (-not $classCode -or $classCode -eq '.') {
    $classCode = [System.IO.Path]::GetFileNameWithoutExtension($sourceFile)
  }
  $outPath = if ($outputFile) { $outputFile } else { Join-Path $outputDirectory ("{0}-平时成绩记分册.xls" -f $classCode) }
  $outParent = Split-Path -Parent $outPath
  if ($outParent) { New-Item -ItemType Directory -Path $outParent -Force | Out-Null }
  Copy-Item -LiteralPath $TemplatePath -Destination $outPath -Force

  $wb = $excel.Workbooks.Open($outPath)
  try {
    $wb.CheckCompatibility = $false
    $structure = $ManifestData.structure
    $columns = $structure.columns
    $ws = $wb.Worksheets.Item([string]$structure.worksheet)
    $hasSkill = $meta.SkillPct -gt 0.000001
    $skillStartCol = ColumnToNumber ([string]$columns.skill_score)
    $skillWeightedCol = ColumnToNumber ([string]$columns.skill_weighted)
    if (-not $hasSkill) {
      $null = $ws.Columns.Item("$($columns.skill_score):$($columns.skill_weighted)").Delete()
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
    $ws.Range([string]$structure.headers.regular).Value2 = ('平时成绩({0}%)' -f [int]($meta.RegularPct * 100))
    $ws.Range([string]$structure.headers.theory).Value2 = ('理论成绩({0}%)' -f [int]($meta.TheoryPct * 100))
    if ($hasSkill) {
      $ws.Range([string]$structure.headers.skill).Value2 = ('技能成绩（{0}%）' -f [int]($meta.SkillPct * 100))
    } else {
      $ws.Columns.Item([string]$structure.no_skill_total_column).ColumnWidth = 18
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

    $ws.Range("$($columns.regular_weighted)${dataStart}:$($columns.regular_weighted)${templateLastDataRow}").NumberFormatLocal = '0.0_ '
    $ws.Range("$($columns.theory_weighted)${dataStart}:$($columns.theory_weighted)${templateLastDataRow}").NumberFormatLocal = '0.0_ '
    if ($hasSkill) {
      $ws.Range("$($columns.skill_weighted)${dataStart}:$($columns.skill_weighted)${templateLastDataRow}").NumberFormatLocal = '0.0_ '
      $ws.Range("$($columns.total_score)${dataStart}:$($columns.total_score)${templateLastDataRow}").NumberFormatLocal = '0_ '
    } else {
      $ws.Range("$($structure.no_skill_total_column)${dataStart}:$($structure.no_skill_total_column)${templateLastDataRow}").NumberFormatLocal = '0_ '
    }
    $firstExtraRow = $dataStart + $students.Count
    if ($firstExtraRow -le $templateLastDataRow) {
      $null = $ws.Range("${firstCol}${firstExtraRow}:${firstCol}${templateLastDataRow}").EntireRow.Delete()
    }
    $excel.CalculateFullRebuild()
    $wb.Save()
  } finally {
    $wb.Close($true)
  }

  $normalizedStudents = @($students | ForEach-Object {
    [ordered]@{
      id = [string]$_.Id
      name = [string]$_.Name
      regular = [double]$_.Regular
      theory = [double]$_.Theory
      skill = [double]$_.Skill
      total = [double]$_.Total
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

  [pscustomobject]@{
    Source = $sourceFile
    Output = $outPath
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
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.AskToUpdateLinks = $false
$results = @()
try {
  foreach ($source in $sources) {
    $buildOutputFile = if ($OutputFile) { $OutputFile } else { '' }
    $builtValues = @(Build-One $excel $source.FullName $OutputDir $buildOutputFile)
    foreach ($builtValue in $builtValues) {
      if ($null -ne $builtValue -and $null -ne $builtValue.PSObject.Properties['Output']) {
        $results += $builtValue
      }
    }
  }
} finally {
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
}

$normalizedJsonPath = Join-Path ([System.IO.Path]::GetTempPath()) ("gradebook-input-" + [guid]::NewGuid().ToString('N') + '.json')
try {
  $validationArgs = @(
    '--manifest', $ManifestPath,
    '--schema', $SchemaPath,
    '--template-path', $TemplatePath,
    '--engine', 'excel-com'
  )
  if ($TemplateWasProvided) { $validationArgs += '--custom-template' }
  if ($SkipTemplateValidation) { $validationArgs += '--skip-template-validation' }
  if (-not $SkipOutputValidation) {
    if ($results.Count -ne 1) {
      Write-Warning 'Batch output validation uses one temporary validation directory per generated workbook.'
      foreach ($result in $results) {
        $validationDir = Join-Path ([System.IO.Path]::GetTempPath()) ("gradebook-validation-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $validationDir -Force | Out-Null
        try {
          $validationFile = Join-Path $validationDir (Split-Path -Leaf $result.Output)
          Copy-Item -LiteralPath $result.Output -Destination $validationFile -Force
          $result.NormalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $normalizedJsonPath -Encoding UTF8
          $runArgs = @('--input-json', $normalizedJsonPath, '--output-dir', $validationDir, '--output-file', $validationFile) + $validationArgs
          & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @runArgs
          if ($LASTEXITCODE -ne 0) { throw "Output validation failed: $($result.Output)" }
        } finally {
          Remove-Item -LiteralPath $validationDir -Recurse -Force -ErrorAction SilentlyContinue
        }
      }
    } else {
      $results[0].NormalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $normalizedJsonPath -Encoding UTF8
      $qaPath = if ($QaReportPath) { $QaReportPath } else { Join-Path $OutputDir 'qa-report.json' }
      $runArgs = @('--input-json', $normalizedJsonPath, '--output-dir', $OutputDir, '--output-file', $results[0].Output, '--qa-report', $qaPath) + $validationArgs
      & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @runArgs
      if ($LASTEXITCODE -ne 0) { throw 'Output validation failed.' }
    }
  } else {
    if ($results.Count -ne 1) {
      foreach ($result in $results) {
        $result.NormalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $normalizedJsonPath -Encoding UTF8
        $qaPath = Join-Path $OutputDir (([System.IO.Path]::GetFileNameWithoutExtension($result.Output)) + '.qa-report.json')
        $runArgs = @('--input-json', $normalizedJsonPath, '--output-dir', $OutputDir, '--output-file', $result.Output, '--qa-report', $qaPath, '--skip-validation') + $validationArgs
        & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @runArgs
        if ($LASTEXITCODE -ne 0) { throw "Could not write skipped QA report: $($result.Output)" }
      }
    } else {
      $result = $results[0]
      $result.NormalizedInput | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $normalizedJsonPath -Encoding UTF8
      $qaPath = if ($QaReportPath) { $QaReportPath } else { Join-Path $OutputDir 'qa-report.json' }
      $runArgs = @('--input-json', $normalizedJsonPath, '--output-dir', $OutputDir, '--output-file', $result.Output, '--qa-report', $qaPath, '--skip-validation') + $validationArgs
      & $PythonCommand (Join-Path $PSScriptRoot 'validate_output.py') @runArgs
      if ($LASTEXITCODE -ne 0) { throw 'Could not write skipped QA report.' }
    }
    Write-Warning 'Output validation skipped; QA report status is skipped.'
  }
} finally {
  Remove-Item -LiteralPath $normalizedJsonPath -Force -ErrorAction SilentlyContinue
}

foreach ($result in $results) {
  $result.PSObject.Properties.Remove('NormalizedInput')
}
$results | ConvertTo-Json -Depth 4



