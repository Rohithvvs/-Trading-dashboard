"""Evidence-only filtering shared by every live indicator path; no raw mutations."""
import json
from pathlib import Path
POLICY=json.loads(Path(__file__).with_name('session_input_policy.json').read_text())
EVIDENCE=json.loads(Path(__file__).with_name('session_input_evidence.json').read_text())
SCHEMA="CREATE TABLE IF NOT EXISTS paper_input_policies(version TEXT PRIMARY KEY,policy_json TEXT NOT NULL); CREATE TABLE IF NOT EXISTS paper_entry_input_proofs(namespace TEXT NOT NULL,signal_id TEXT NOT NULL,policy_version TEXT NOT NULL,bar_date TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(namespace,signal_id)); CREATE TABLE IF NOT EXISTS paper_input_evidence(version TEXT PRIMARY KEY,policy_version TEXT NOT NULL,evidence_json TEXT NOT NULL);"
def init(db):
 for sql in SCHEMA.split(';'):
  if sql.strip():db.query(sql)
 value=json.dumps(POLICY,sort_keys=True,separators=(',',':'))
 db.query('INSERT OR IGNORE INTO paper_input_policies VALUES(?,?)',(POLICY['version'],value))
 if db.query('SELECT policy_json FROM paper_input_policies WHERE version=?',(POLICY['version'],))[0]['policy_json']!=value:raise RuntimeError('immutable_input_policy_changed')
 evidence=json.dumps(EVIDENCE,sort_keys=True,separators=(',',':'))
 db.query('INSERT OR IGNORE INTO paper_input_evidence VALUES(?,?,?)',(EVIDENCE['version'],POLICY['version'],evidence))
 if db.query('SELECT evidence_json FROM paper_input_evidence WHERE version=?',(EVIDENCE['version'],))[0]['evidence_json']!=evidence:raise RuntimeError('immutable_input_evidence_changed')
def filter_history(frame,benchmark):
 dates=frame.trade_date.astype(str);excluded=dates.isin(POLICY['closed_dates']);clean=frame.loc[~excluded].copy();details={}
 bdates=set(benchmark.trade_date.astype(str)) if benchmark is not None and len(benchmark) else set();start=min(sorted(bdates)[-253:]) if bdates else None
 for sym,g in frame.groupby('symbol'):
  ds=g.trade_date.astype(str);bad=ds.isin(POLICY['closed_dates']);remaining=ds[~bad]
  uncertain=sorted({d for d in remaining if start and start<=d<=max(bdates) and d not in bdates})
  details[sym]={'version':POLICY['version'],'excluded_rows':int(bad.sum()),'excluded_dates':sorted(set(ds[bad])),'legacy_before_coverage_rows_retained':int((remaining<POLICY['coverage_from']).sum()),'unverified_recent_dates':uncertain,'coverage_from':POLICY['coverage_from'],'coverage_through':POLICY['coverage_through'],'full_warmup_retained':True}
 audit={'policy':POLICY,'raw_rows':len(frame),'live_rows':len(clean),'excluded_rows':int(excluded.sum()),'excluded_by_date':{d:int(n) for d,n in dates[excluded].value_counts().sort_index().items()},'legacy_before_coverage_rows_retained':sum(d['legacy_before_coverage_rows_retained'] for d in details.values()),'unverified_recent_symbols':sum(bool(d['unverified_recent_dates']) for d in details.values()),'raw_rows_mutated':False}
 return clean,details,audit
