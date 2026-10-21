"""Run the real unittest suite and save its observed results."""
from datetime import datetime, timezone
import io,json,platform
from pathlib import Path
import sys,time,unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
start=time.perf_counter()
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
elapsed=time.perf_counter()-start
report={
    'timestamp':datetime.now(timezone.utc).isoformat(),
    'python':platform.python_version(),'platform':platform.platform(),
    'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
    'skipped':len(result.skipped),'elapsed_seconds':round(elapsed,4),
    'kmp_exhaustive_pairs':255*31,'prefix_definition_cases':255,
    'seeded_byte_roundtrips':180,'exhaustive_merge_oracle_cases':40,
}
(root/'docs').mkdir(exist_ok=True)
(root/'docs'/'test-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
(root/'docs'/'test-output.txt').write_text(stream.getvalue(),encoding='utf-8')
print(json.dumps(report,indent=2))
sys.exit(0 if result.wasSuccessful() else 1)
