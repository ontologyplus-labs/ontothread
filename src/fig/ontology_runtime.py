"""Immutable runtime ontology selection and relationship validation."""
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeOntology:
    version: str
    schema_hash: str
    definitions: dict[str, Any]

    @classmethod
    def from_store(cls,store,version=None):
        versions=store.ontology_versions()["versions"]
        if not versions:raise ValueError("no ontology versions are installed")
        row=next((item for item in versions if item["version"]==version),None) if version else versions[-1]
        if not row:raise KeyError("ontology version not found")
        return cls(row["version"],row["schema_hash"],json.loads(json.dumps(row["definitions"])))

    def relationship_errors(self,subject_kind,predicate,object_kind):
        rule=self.definitions.get("predicates",{}).get(predicate)
        if not rule:return [f"Predicate {predicate} is not defined in {self.version}."]
        errors=[]
        if subject_kind not in rule.get("subject",[]):errors.append(f"Subject kind {subject_kind} is not allowed for {predicate}.")
        if object_kind not in rule.get("object",[]):errors.append(f"Object kind {object_kind} is not allowed for {predicate}.")
        return errors

    def validate_relationship(self,subject_kind,predicate,object_kind):
        errors=self.relationship_errors(subject_kind,predicate,object_kind)
        if errors:raise ValueError(" ".join(errors))
        return {"ontology_version":self.version,"schema_hash":self.schema_hash,"predicate":predicate,
                "subject_kind":subject_kind,"object_kind":object_kind,"valid":True}

    def permits_predicate(self,predicate):
        return predicate in self.definitions.get("predicates",{})
