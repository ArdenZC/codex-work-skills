param(
  [Parameter(Mandatory=$true)]
  [string]$SourcePath,

  [Parameter(Mandatory=$false)]
  [string]$OutputDir = "",

  [Parameter(Mandatory=$false)]
  [string]$TemplatePath = ""
)

$ErrorActionPreference = 'Stop'

if (-not $TemplatePath) {
  $TemplatePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\平时成绩记分册模板.xls'
}

if (-not (Test-Path -LiteralPath $TemplatePath)) {
  throw "Template not found: $TemplatePath"
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
  $line2 = [string]$sheet.Cells.Item(2, 1).Value2
  $line3 = [string]$sheet.Cells.Item(3, 1).Value2
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

function HeaderMap($sheet, [int]$startCol, [int]$endCol) {
  $map = @{}
  for ($c = $startCol; $c -le $endCol; $c++) {
    $h = ([string]$sheet.Cells.Item(4, $c).Text).Trim()
    if ($h) { $map[$h] = $c }
  }
  return $map
}

function Read-Students($sheet) {
  $used = $sheet.UsedRange
  $rows = $used.Rows.Count
  $cols = $used.Columns.Count
  $starts = @()
  for ($c = 1; $c -le $cols; $c++) {
    if ((([string]$sheet.Cells.Item(4, $c).Text).Trim() -eq '学号') -and
        (([string]$sheet.Cells.Item(4, $c + 1).Text).Trim() -eq '姓名')) {
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
    $blocks += [pscustomobject]@{ Start = $start; Map = (HeaderMap $sheet $start $end) }
  }

  $students = New-Object System.Collections.Generic.List[object]
  for ($r = 5; $r -le $rows; $r++) {
    foreach ($block in $blocks) {
      $start = [int]$block.Start
      $map = $block.Map
      $id = ([string]$sheet.Cells.Item($r, $start).Text).Trim()
      $name = ([string]$sheet.Cells.Item($r, $start + 1).Text).Trim()
      if ($id -notmatch '^\d{8,}$' -or -not $name) { continue }
      if (-not $map.ContainsKey('理论成绩') -or -not $map.ContainsKey('平时成绩') -or -not $map.ContainsKey('总成绩')) {
        throw "Source block is missing 理论成绩/平时成绩/总成绩 headers."
      }
      $students.Add([pscustomobject]@{
        Id = $id
        Name = $name
        Skill = if ($map.ContainsKey('技能成绩')) { To-Number $sheet.Cells.Item($r, $map['技能成绩']).Value2 } else { 0.0 }
        Theory = To-Number $sheet.Cells.Item($r, $map['理论成绩']).Value2
        Regular = To-Number $sheet.Cells.Item($r, $map['平时成绩']).Value2
        Total = To-Number $sheet.Cells.Item($r, $map['总成绩']).Value2
      })
    }
  }
  if ($students.Count -eq 0) {
    throw "No students parsed from source workbook."
  }
  return $students
}

function Get-StableSeed([string]$text) {
  $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
  return [System.BitConverter]::ToInt32($hash, 0) -band 0x7fffffff
}

function Generate-RegularScores([double]$target, [string]$seedText) {
  $targetUnits = [int][Math]::Round($target * 2)
  $targetTotalUnits = $targetUnits * 8
  $rand = [System.Random]::new((Get-StableSeed $seedText))
  for ($attempt = 0; $attempt -lt 2000; $attempt++) {
    $scores = New-Object System.Collections.Generic.List[int]
    $sum = 0
    for ($i = 0; $i -lt 7; $i++) {
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
  return @(1..8 | ForEach-Object { $target })
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

function Build-One($excel, [string]$sourceFile, [string]$outputDirectory) {
  $srcWb = $excel.Workbooks.Open($sourceFile, 0, $true)
  try {
    $srcSheet = $srcWb.Worksheets.Item(1)
    $meta = Read-Meta $srcSheet
    $students = @(Read-Students $srcSheet)
  } finally {
    $srcWb.Close($false)
  }

  $classCode = Split-Path -Leaf (Split-Path -Parent $sourceFile)
  if (-not $classCode -or $classCode -eq '.') {
    $classCode = [System.IO.Path]::GetFileNameWithoutExtension($sourceFile)
  }
  $outPath = Join-Path $outputDirectory ("{0}-平时成绩记分册.xls" -f $classCode)
  Copy-Item -LiteralPath $TemplatePath -Destination $outPath -Force

  $wb = $excel.Workbooks.Open($outPath)
  try {
    $wb.CheckCompatibility = $false
    $ws = $wb.Worksheets.Item('平时成绩')
    $hasSkill = $meta.SkillPct -gt 0.000001
    if (-not $hasSkill) {
      $null = $ws.Columns.Item('O:P').Delete()
    }

    $dataStart = 5
    $templateLastDataRow = 52
    if ($students.Count -gt ($templateLastDataRow - $dataStart + 1)) {
      $needed = $students.Count - ($templateLastDataRow - $dataStart + 1)
      for ($i = 0; $i -lt $needed; $i++) {
        $insertAt = $templateLastDataRow + 1
        $ws.Rows.Item($templateLastDataRow).Copy()
        $ws.Rows.Item($insertAt).Insert(-4121)
        $templateLastDataRow++
      }
    }

    $lastCol = if ($hasSkill) { 'Q' } else { 'O' }
    $ws.Range("A${dataStart}:${lastCol}${templateLastDataRow}").ClearContents()
    $ws.Cells.Item(2, 3).Value2 = $meta.Term
    $ws.Cells.Item(2, 7).Value2 = $meta.CourseName
    $ws.Cells.Item(2, 12).Value2 = $meta.Teacher
    $ws.Cells.Item(2, 15).Value2 = $meta.ClassName
    $ws.Cells.Item(3, 4).Value2 = ('平时成绩({0}%)' -f [int]($meta.RegularPct * 100))
    $ws.Cells.Item(3, 13).Value2 = ('理论成绩({0}%)' -f [int]($meta.TheoryPct * 100))
    if ($hasSkill) {
      $ws.Cells.Item(3, 15).Value2 = ('技能成绩（{0}%）' -f [int]($meta.SkillPct * 100))
    } else {
      $ws.Columns.Item('O').ColumnWidth = 18
    }

    $regularPct = FormulaNumber $meta.RegularPct
    $theoryPct = FormulaNumber $meta.TheoryPct
    $skillPct = FormulaNumber $meta.SkillPct

    for ($i = 0; $i -lt $students.Count; $i++) {
      $student = $students[$i]
      $r = $dataStart + $i
      $scores = Generate-RegularScores $student.Regular ("$classCode|$($student.Id)|$($student.Regular)")
      Set-Value $ws $r 1 ([double]($i + 1))
      $ws.Range((CellAddress $r 2)).NumberFormatLocal = '@'
      Set-Value $ws $r 2 $student.Id
      Set-Value $ws $r 3 $student.Name
      for ($j = 0; $j -lt 8; $j++) {
        Set-Value $ws $r (4 + $j) ([double]$scores[$j])
      }
      Set-Formula $ws $r 12 "=AVERAGE(D$r`:K$r)*$regularPct"
      Set-Value $ws $r 13 ([System.Convert]::ToDouble($student.Theory))
      Set-Formula $ws $r 14 "=M$r*$theoryPct"
      if ($hasSkill) {
        Set-Value $ws $r 15 ([System.Convert]::ToDouble($student.Skill))
        Set-Formula $ws $r 16 "=O$r*$skillPct"
        Set-Formula $ws $r 17 "=ROUND(AVERAGE(D$r`:K$r)*$regularPct+M$r*$theoryPct+O$r*$skillPct,0)"
      } else {
        Set-Formula $ws $r 15 "=ROUND(AVERAGE(D$r`:K$r)*$regularPct+M$r*$theoryPct,0)"
      }
    }

    $ws.Range("L${dataStart}:L${templateLastDataRow}").NumberFormatLocal = '0.0_ '
    $ws.Range("N${dataStart}:N${templateLastDataRow}").NumberFormatLocal = '0.0_ '
    if ($hasSkill) {
      $ws.Range("P${dataStart}:P${templateLastDataRow}").NumberFormatLocal = '0.0_ '
      $ws.Range("Q${dataStart}:Q${templateLastDataRow}").NumberFormatLocal = '0_ '
    } else {
      $ws.Range("O${dataStart}:O${templateLastDataRow}").NumberFormatLocal = '0_ '
    }
    $firstExtraRow = $dataStart + $students.Count
    if ($firstExtraRow -le $templateLastDataRow) {
      $null = $ws.Range("A${firstExtraRow}:A${templateLastDataRow}").EntireRow.Delete()
    }
    $excel.CalculateFullRebuild()
    $wb.Save()
  } finally {
    $wb.Close($true)
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
  }
}

$sources = Resolve-SourceFiles $SourcePath
if (-not $OutputDir) {
  $OutputDir = Join-Path (Split-Path -Parent $sources[0].FullName) '平时成绩记分册_生成'
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.AskToUpdateLinks = $false
$results = @()
try {
  foreach ($source in $sources) {
    $results += Build-One $excel $source.FullName $OutputDir
  }
} finally {
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
}

$results | ConvertTo-Json -Depth 4



