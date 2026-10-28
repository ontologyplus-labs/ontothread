"""Persist and audit review-only structured event candidates."""
import json
from datetime import datetime,timezone
from uuid import uuid4,uuid5,NAMESPACE_URL

from fig.analysis import PassageAnalyzer

class EventReviewConflict(ValueError):pass

def stamp():return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")

class EventReview:
    def __init__(self,store):self.store=store;self.analyzer=PassageAnalyzer(store)

    def analyze(self,passage_ids):
        analysis=self.analyzer.analyze(passage_ids);ids=[]
        with self.store.connect() as conn:
            for result in analysis["results"]:
                for event in result["event_candidates"]:
                    key=f"{result['passage_id']}:{event['event_type']}:{event['start_offset']}:{event['end_offset']}:{event['company_id']}"
                    candidate_id=str(uuid5(NAMESPACE_URL,"fig:event:"+key));ids.append(candidate_id)
                    payload={**event,"id":candidate_id,"passage_id":result["passage_id"],"state":"pending","version":1}
                    self.store.execute(conn,"INSERT INTO event_candidate VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                                       (candidate_id,result["passage_id"],event["company_id"],event["event_type"],"pending",1,json.dumps(payload,sort_keys=True)))
        return {"candidate_ids":ids,"analysis":analysis}

    def list(self,state="all",limit=100,offset=0):
        where="";args=[]
        if state!="all":where=" WHERE state=?";args=[state]
        with self.store.connect() as conn:
            rows=self.store.execute(conn,"SELECT * FROM event_candidate"+where+" ORDER BY id LIMIT ? OFFSET ?",(*args,limit+1,offset)).fetchall()
        return {"candidates":[{**json.loads(row["payload"]),"state":row["state"],"version":row["version"]} for row in rows[:limit]],"truncated":len(rows)>limit,"next_offset":offset+limit if len(rows)>limit else None}

    def decide(self,candidate_id,decision):
        with self.store.connect() as conn:
            row=self.store.execute(conn,"SELECT * FROM event_candidate WHERE id=?"+("" if self.store.fixture_mode else " FOR UPDATE"),(str(candidate_id),)).fetchone()
            if not row:raise KeyError("event candidate not found")
            if row["state"]!="pending" or row["version"]!=decision.expected_version:raise EventReviewConflict("Event candidate changed or was already reviewed.")
            state="accepted" if decision.action=="accept" else "rejected";payload=json.loads(row["payload"]);payload.update(state=state,version=row["version"]+1)
            self.store.execute(conn,"UPDATE event_candidate SET state=?,version=version+1,payload=? WHERE id=?",(state,json.dumps(payload,sort_keys=True),str(candidate_id)))
            audit={**decision.model_dump(mode="json"),"candidate_id":str(candidate_id),"decided_at":stamp()}
            self.store.execute(conn,"INSERT INTO event_review_decision VALUES (?,?,?,?)",(str(uuid4()),str(candidate_id),decision.expected_version,json.dumps(audit,sort_keys=True)))
        return payload

    def history(self,candidate_id):
        with self.store.connect() as conn:
            if not self.store.execute(conn,"SELECT id FROM event_candidate WHERE id=?",(str(candidate_id),)).fetchone():raise KeyError("event candidate not found")
            rows=self.store.execute(conn,"SELECT payload FROM event_review_decision WHERE candidate_id=? ORDER BY candidate_version",(str(candidate_id),)).fetchall()
        return {"decisions":[json.loads(row["payload"]) for row in rows]}
