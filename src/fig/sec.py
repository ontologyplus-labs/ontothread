"""Bounded SEC transport with identifying headers and a shared local rate limit."""
import base64
import fcntl
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import httpx

class SecError(RuntimeError):
    pass

@dataclass(frozen=True)
class Download:
    body: bytes
    acquired_at: datetime
    url: str

class FileRateLimiter:
    """Coordinates processes using the same cache volume; defaults to 2 req/s."""
    def __init__(self, path, interval=0.5):
        self.path=Path(path)
        self.interval=interval

    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a+") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            lock.seek(0)
            previous=float(lock.read() or 0)
            # Wall time lets independent processes share the persisted clock.
            delay=max(0,min(self.interval,previous+self.interval-time.time()))
            if delay:
                time.sleep(delay)
            lock.seek(0)
            lock.truncate()
            lock.write(str(time.time()))
            lock.flush()
            fcntl.flock(lock,fcntl.LOCK_UN)

class SecClient:
    def __init__(self, user_agent, cache_dir, *, transport=None, limiter=None, sleep=time.sleep,max_response_bytes=100*1024*1024):
        if not user_agent or "\n" in user_agent or "\r" in user_agent or not re.search(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}",user_agent):
            raise ValueError("SEC_USER_AGENT must contain an application name and contact email")
        if re.search(r"@(example\.(com|org|net)|[^\s]+\.invalid)(?:\s|$)",user_agent,re.I):
            raise ValueError("Replace the placeholder SEC contact email before live access")
        self.cache=Path(cache_dir)
        self.limiter=limiter or FileRateLimiter(self.cache/"request-rate.lock")
        self.sleep=sleep
        if not 1024*1024<=max_response_bytes<=200*1024*1024:raise ValueError("SEC response limit must be between 1 MiB and 200 MiB")
        self.max_response_bytes=max_response_bytes
        self.http=httpx.Client(transport=transport,timeout=30,follow_redirects=False,
                               headers={"User-Agent":user_agent,"Accept-Encoding":"identity"})

    def close(self):
        self.http.close()

    @staticmethod
    def validate_url(url):
        parts=urlsplit(url)
        data_path=parts.hostname=="data.sec.gov" and (
            parts.path.startswith("/submissions/") or
            bool(re.fullmatch(r"/api/xbrl/companyfacts/CIK[0-9]{10}\.json",parts.path)))
        allowed=data_path or (parts.hostname=="www.sec.gov" and parts.path.startswith("/Archives/edgar/data/"))
        if parts.scheme!="https" or parts.port not in (None,443) or parts.username or parts.password or parts.query or parts.fragment or not allowed:
            raise ValueError("Only SEC submissions and filing archive URLs are allowed")
        if ".." in parts.path or "%" in parts.path:
            raise ValueError("Invalid SEC path")

    def get(self,url,*,immutable=False):
        self.validate_url(url)
        key=sha256(url.encode()).hexdigest()
        path=self.cache/(key+".json")
        if path.exists():
            try:
                data=json.loads(path.read_text())
                body=base64.b64decode(data["body"],validate=True)
                acquired=datetime.fromisoformat(data["acquired_at"])
                if sha256(body).hexdigest()!=data["sha256"] or data["url"]!=url:
                    raise ValueError("cache integrity")
                if immutable or datetime.now(timezone.utc)-acquired<timedelta(hours=1):
                    return Download(body,acquired,url)
            except (ValueError,KeyError,TypeError):
                pass  # Corrupt cache gets a fresh bounded download.
        for attempt in range(3):
            self.limiter.acquire()
            try:
                with self.http.stream("GET",url) as response:
                    if response.status_code in (429,500,502,503,504):
                        if attempt==2:
                            raise SecError(f"SEC unavailable after 3 attempts (HTTP {response.status_code})")
                        retry=response.headers.get("Retry-After","")
                        try:
                            delay=float(retry) if retry else 2**attempt
                        except ValueError:
                            # Dates or very long server delays are not guessed.
                            raise SecError("SEC requested retry later; rerun the command later") from None
                        if delay>30:
                            raise SecError("SEC requested a long retry delay; rerun later")
                        self.sleep(max(0,delay))
                        continue
                    if response.status_code!=200:
                        raise SecError(f"SEC returned HTTP {response.status_code}; no bypass attempted")
                    chunks=[]
                    size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>self.max_response_bytes:
                            raise SecError(f"SEC response exceeds the {self.max_response_bytes//(1024*1024)} MiB download limit")
                        chunks.append(chunk)
                    body=b"".join(chunks)
                    if not body:
                        raise SecError("SEC returned an empty document")
            except httpx.TransportError as error:
                if attempt==2:
                    raise SecError("SEC network request failed after 3 attempts") from error
                self.sleep(2**attempt)
                continue
            acquired=datetime.now(timezone.utc)
            self.cache.mkdir(parents=True,exist_ok=True)
            entry={"url":url,"acquired_at":acquired.isoformat(),"sha256":sha256(body).hexdigest(),"body":base64.b64encode(body).decode()}
            with tempfile.NamedTemporaryFile(mode="w",dir=self.cache,delete=False) as output:
                temporary=Path(output.name)
                json.dump(entry,output)
            os.replace(temporary,path)
            return Download(body,acquired,url)
        raise SecError("SEC download failed")

    def json(self,url):
        try:
            data=json.loads(self.get(url).body)
            if not isinstance(data,dict):
                raise ValueError("metadata must be an object")
            return data
        except (ValueError,UnicodeDecodeError) as error:
            raise SecError("SEC metadata was not valid JSON") from error

    def latest_annual_filing(self,cik,accession=None):
        cik=str(cik)
        if not re.fullmatch(r"[0-9]{1,10}",cik) or int(cik)==0:
            raise ValueError("CIK must be a positive identifier with up to 10 digits")
        data=self.json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        if str(int(data.get("cik",0)))!=str(int(cik)) or not data.get("name"):
            raise SecError("SEC returned an unexpected issuer identity")
        candidates=[]
        def collect(rows):
            names=("accessionNumber","form","filingDate","primaryDocument")
            if not all(isinstance(rows.get(x),list) for x in names):
                raise SecError("SEC filing metadata lacks required arrays")
            if len({len(rows[x]) for x in names})!=1:
                raise SecError("SEC filing metadata arrays have inconsistent lengths")
            for index,values in enumerate(zip(*(rows[x] for x in names))):
                row=dict(zip(names,values))
                report_dates=rows.get("reportDate")
                if isinstance(report_dates,list) and len(report_dates)==len(rows[names[0]]):
                    row["reportDate"]=report_dates[index]
                if row["form"] in ("10-K","20-F") and (accession is None or row["accessionNumber"]==accession):
                    if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}",row["accessionNumber"]):
                        raise SecError("Invalid filing accession")
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.html?",row["primaryDocument"]):
                        # Historical metadata can contain legacy text/paper filings.
                        # They must not prevent selection of a newer supported HTML
                        # annual report. An explicitly requested unsupported accession
                        # still fails rather than silently selecting another filing.
                        if accession:
                            raise SecError("Primary annual filing is not supported HTML")
                        continue
                    datetime.strptime(row["filingDate"],"%Y-%m-%d")
                    candidates.append(row)
        collect(data.get("filings",{}).get("recent",{}))
        # Older history is read only when a requested accession is absent, or
        # the recent window has no annual report. Bounded to 20 history files.
        if not candidates:
            history=data.get("filings",{}).get("files",[])
            if len(history)>20:
                raise SecError("History search exceeds 20 files; narrow the requested corpus")
            for entry in history:
                name=entry.get("name","")
                if not re.fullmatch(r"CIK[0-9]{10}-submissions-[0-9]+\.json",name):
                    raise SecError("Invalid SEC history filename")
                collect(self.json("https://data.sec.gov/submissions/"+name))
                if accession and candidates:
                    break
        if not candidates:
            raise SecError("No matching annual filing found")
        selected=max(candidates,key=lambda row:(row["filingDate"],row["accessionNumber"]))
        selected.update(cik=str(int(cik)),issuer_name=data["name"])
        selected["source_url"]=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{selected['accessionNumber'].replace('-','')}/{selected['primaryDocument']}"
        return selected

    def annual_filings(self,cik,limit=3):
        """Return a bounded newest-first annual history with supported HTML documents."""
        if not 1<=limit<=10:raise ValueError("Annual filing limit must be between 1 and 10")
        return self.filings(cik,("10-K","20-F"),limit)

    def filings(self,cik,forms=("10-K","10-Q","8-K","DEF 14A","4","20-F","6-K"),limit=20):
        """Return bounded newest-first supported HTML filings for explicit form types."""
        cik=str(cik)
        if not re.fullmatch(r"[0-9]{1,10}",cik) or int(cik)==0:
            raise ValueError("CIK must be a positive identifier with up to 10 digits")
        allowed={"10-K","10-Q","8-K","DEF 14A","4","20-F","6-K"};forms=tuple(dict.fromkeys(forms))
        if not forms or set(forms)-allowed:raise ValueError("Forms must be selected from 10-K, 10-Q, 8-K, DEF 14A, 4, 20-F and 6-K")
        if not 1<=limit<=100:raise ValueError("Filing limit must be between 1 and 100")
        data=self.json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        if str(int(data.get("cik",0)))!=str(int(cik)) or not data.get("name"):
            raise SecError("SEC returned an unexpected issuer identity")
        candidates=[]
        def collect(rows):
            names=("accessionNumber","form","filingDate","primaryDocument")
            if not all(isinstance(rows.get(name),list) for name in names):raise SecError("SEC filing metadata lacks required arrays")
            if len({len(rows[name]) for name in names})!=1:raise SecError("SEC filing metadata arrays have inconsistent lengths")
            for index,values in enumerate(zip(*(rows[name] for name in names))):
                row=dict(zip(names,values))
                report_dates=rows.get("reportDate")
                if isinstance(report_dates,list) and len(report_dates)==len(rows[names[0]]):
                    row["reportDate"]=report_dates[index]
                if row["form"] not in forms:continue
                if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}",row["accessionNumber"]):raise SecError("Invalid filing accession")
                if not re.fullmatch(r"(?:xslF345X0[1-5]/)?[A-Za-z0-9_.-]+\.(?:html?|xml)",row["primaryDocument"]):continue
                datetime.strptime(row["filingDate"],"%Y-%m-%d")
                candidates.append(row)
        collect(data.get("filings",{}).get("recent",{}))
        history=data.get("filings",{}).get("files",[])
        if len(history)>20:raise SecError("History search exceeds 20 files; narrow the requested corpus")
        for entry in history:
            if len({item["accessionNumber"] for item in candidates})>=limit:break
            name=entry.get("name","")
            if not re.fullmatch(r"CIK[0-9]{10}-submissions-[0-9]+\.json",name):raise SecError("Invalid SEC history filename")
            collect(self.json("https://data.sec.gov/submissions/"+name))
        unique={row["accessionNumber"]:row for row in candidates}
        selected=sorted(unique.values(),key=lambda row:(row["filingDate"],row["accessionNumber"]),reverse=True)[:limit]
        if not selected:raise SecError("No matching supported filing found")
        for row in selected:
            row.update(cik=str(int(cik)),issuer_name=data["name"])
            row["source_url"]=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{row['accessionNumber'].replace('-','')}/{row['primaryDocument']}"
        return selected
