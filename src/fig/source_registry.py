from pathlib import Path
from urllib.parse import urlparse
import yaml

APPROVALS={"pending_review","approved","rejected","link_only"}
OFFICIAL_HOSTS={"investor.nvidia.com","ir.amd.com","investors.broadcom.com","www.investor.asml.com","investor.tsmc.com"}

def load_source_registry(path):
    data=yaml.safe_load(Path(path).read_text())
    if data.get("version")!="non-sec-source-registry-v1":raise ValueError("unsupported source registry version")
    seen=set()
    for source in data.get("sources",[]):
        host=(urlparse(source["url"]).hostname or "").casefold()
        if host not in OFFICIAL_HOSTS:raise ValueError("source registry requires an approved official host")
        if source["archive_policy"] not in APPROVALS or source["extraction_policy"] not in APPROVALS:raise ValueError("invalid source approval state")
        key=(source["cik"],source["url"])
        if key in seen:raise ValueError("duplicate source registry entry")
        seen.add(key)
    return data

def ingestible_sources(path):
    data=load_source_registry(path)
    return [source for source in data["sources"] if source["archive_policy"]=="approved" and source["extraction_policy"]=="approved"]
