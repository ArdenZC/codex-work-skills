# Test execution lanes

The repository's complete regression suite deliberately exercises real template
files, archive/release transactions, LibreOffice, and (on Windows) Office COM.
Those checks are expensive, so local runs should use the same semantic
boundaries as CI instead of running every module in one serial interpreter.

## Shard runner

Use `.github/scripts/run_test_shards.py` to inspect the exact manifest:

```text
python .github/scripts/run_test_shards.py --list
```

The `full` alias is an exact partition of root `tests/test_*.py` discovery.
The `fast` alias covers Content Contract V2, package/workflow contracts, the
change classifier, and the runner manifest. `ci` additionally runs the two
skill test directories. Each worker receives its own `TEMP`/`TMP`, Python cache
root, and Office profile. Put artifacts on a non-system volume when possible:

```text
python .github/scripts/run_test_shards.py \
  --suite fast --parallel --root F:\\test-artifacts\\codex-fast

python .github/scripts/run_test_shards.py \
  --suite full --parallel --root F:\\test-artifacts\\codex-full
```

`--parallel` overlaps only shards marked safe. Lesson package, Gradebook, and
release shards remain serialized because they exercise Office/LibreOffice and
failure-recovery boundaries. `--allow-office-parallel` is an explicit opt-in
for a machine with independently isolated Office profiles; it is not the
default CI mode.

The runner prints one duration and log path per shard. `--keep-artifacts`
retains logs for diagnosis. A Windows release shard must use a standalone
Python executable when the tests need to copy `sys.executable` as a fake
`gh.exe`; a venv interpreter without its adjacent `pyvenv.cfg` is not a valid
standalone test executable.

This is a scheduling and isolation optimization only. It does not remove
tests, replace real Office/render checks with stubs, weaken Content QA, or
change template compatibility and canonical fingerprints.
