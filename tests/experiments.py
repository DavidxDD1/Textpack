"""Reproducible compression observations and adversarial search comparisons."""
from datetime import datetime,timezone
from pathlib import Path
import gzip,json,platform,random,statistics,sys,time
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from textpack.codec import compress,decompress,describe
from textpack.kmp import find_all

class CountedChar(str):
    comparisons=0
    def __eq__(self,other):
        CountedChar.comparisons+=1
        return str.__eq__(self,other)
    def __ne__(self,other):
        CountedChar.comparisons+=1
        return str.__ne__(self,other)

def naive(text,pattern):
    positions=[]
    if not pattern:return positions
    for i in range(len(text)-len(pattern)+1):
        for j in range(len(pattern)):
            if text[i+j]!=pattern[j]:break
        else:positions.append(i)
    return positions

def median_ms(function,*args):
    observed=[]
    for _ in range(5):
        start=time.perf_counter();function(*args);observed.append((time.perf_counter()-start)*1000)
    return round(statistics.median(observed),4)

search=[]
for n in [2000,4000,8000,16000]:
    text='a'*n;pattern='a'*63+'b'
    CountedChar.comparisons=0
    actual=find_all(list(map(CountedChar,text)),list(map(CountedChar,pattern)))
    kmp_count=CountedChar.comparisons
    CountedChar.comparisons=0
    expected=naive(list(map(CountedChar,text)),list(map(CountedChar,pattern)))
    naive_count=CountedChar.comparisons
    assert actual==expected==[]
    search.append({'text_length':n,'pattern_length':64,'kmp_comparisons':kmp_count,'naive_comparisons':naive_count,'kmp_ms':median_ms(find_all,text,pattern),'naive_ms':median_ms(naive,text,pattern)})
rng=random.Random(2026)
cases={'empty':b'','banana':b'banana','all_256_bytes':bytes(range(256)),'study_notes':(root/'examples'/'study_notes.txt').read_bytes(),'seeded_random_4096':bytes(rng.randrange(256) for _ in range(4096))}
compression=[]
for label,data in cases.items():
    archive=compress(data)
    assert decompress(archive)==data
    info=describe(data,archive)
    compression.append({'case':label,**{key:info[key] for key in ['original_bytes','archive_bytes','metadata_bytes','payload_bytes','saving_percent']},'gzip_bytes':len(gzip.compress(data,mtime=0)),'roundtrip_ok':True})
report={'timestamp':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'platform':platform.platform(),'timing_runs':5,'search':search,'compression':compression}
(root/'docs'/'experiment-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
