"""Persistent identities for conservatively projected, source-authoritative fields."""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from uuid import uuid4

from .document import digest

VERSION = 1
MAX_NODES = 400
MAX_METADATA_BYTES = 131072
_ID = re.compile(r"imported\.[0-9a-f]{32}\Z")


def _record(node: dict, source: str) -> dict:
    span = node["source_span"]
    start, end = span["start"], span["end"]
    if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or not 0 <= start < end <= len(source)
            or not isinstance(node["text"], str)):
        raise ValueError("Invalid imported identity span")
    return {"node_id": node["node_id"], "kind": node["kind"], "section": node["section"],
            "encoding": node.get("_encoding", "literal"), "text": node["text"],
            "raw": source[start:end], "start": start, "end": end}


def _signature(record: dict) -> tuple:
    return tuple(record[key] for key in ("kind", "section", "encoding", "text", "raw"))


def _set_identity(node: dict, identity: str) -> None:
    node["node_id"] = identity
    node["node_revision"] = digest(identity + "\0" + node["text"])


def bind_projection(document: dict, metadata) -> dict:
    """Use IDs only when every stored record matches a fresh exact-source projection."""
    if document["source_mode"] != "imported" or not isinstance(metadata, dict):
        return document
    try:
        keys = {"version", "document_id", "owner_scope", "source_sha256", "nodes"}
        if (set(metadata) not in (keys, keys | {"opaque"})
                or not isinstance(metadata["version"], int) or isinstance(metadata["version"], bool) or metadata["version"] != VERSION
                or metadata["source_sha256"] != document["source_sha256"]
                or metadata["document_id"] != document["document_id"] or metadata["owner_scope"] != document["owner_scope"]
                or len(json.dumps(metadata, ensure_ascii=False).encode()) > MAX_METADATA_BYTES
                or not isinstance(metadata["nodes"], list) or len(metadata["nodes"]) > MAX_NODES
                ):
            return document
        if metadata.get("opaque") is True and metadata["nodes"] == []:
            result = copy.deepcopy(document)
            result["nodes"] = []
            result["_identity_opaque"] = True
            result["opaque_blocks"].append({"start": 0, "end": len(result["_source"]), "reason": "Imported identity projection exceeds its bounded support profile"})
            return result
        if "opaque" in metadata or len(metadata["nodes"]) != len(document["nodes"]):
            return document
        identities = set()
        mapping = []
        for node, stored in zip(document["nodes"], metadata["nodes"], strict=True):
            fresh = _record(node, document["_source"])
            if (not isinstance(stored, dict) or set(stored) != set(fresh)
                    or not isinstance(stored["node_id"], str) or not _ID.fullmatch(stored["node_id"])
                    or stored["node_id"] in identities
                    or {k: v for k, v in fresh.items() if k != "node_id"}
                    != {k: v for k, v in stored.items() if k != "node_id"}):
                return document
            identities.add(stored["node_id"])
            mapping.append(stored["node_id"])
        result = copy.deepcopy(document)
        for node, identity in zip(result["nodes"], mapping, strict=True):
            _set_identity(node, identity)
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        return document


def seed_projection(document: dict) -> tuple[dict, dict | None]:
    """Generate IDs once for persistence, never call text hashes persistent IDs."""
    if document["source_mode"] != "imported":
        return document, None
    result = copy.deepcopy(document)
    for node in result["nodes"]:
        _set_identity(node, "imported." + uuid4().hex)
    try:
        metadata = metadata_for(result)
    except ValueError:
        result["nodes"] = []
        result["_identity_opaque"] = True
        result["opaque_blocks"].append({"start": 0, "end": len(result["_source"]), "reason": "Imported identity projection exceeds its bounded support profile"})
        metadata = metadata_for(result)
    return result, metadata


def metadata_for(document: dict) -> dict:
    metadata = {"version": VERSION, "document_id": document["document_id"], "owner_scope": document["owner_scope"],
                "source_sha256": document["source_sha256"],
                "nodes": [_record(node, document["_source"]) for node in document["nodes"]]}
    if document.get("_identity_opaque"):
        metadata["opaque"] = True
    if len(metadata["nodes"]) > MAX_NODES or len(json.dumps(metadata, ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
        raise ValueError("Imported identity metadata budget exceeded")
    return metadata


def reconcile_projection(document: dict, previous: dict, approved_patches: list[dict] | None = None) -> tuple[dict, dict | None]:
    """Retain unique unchanged fields or exact server-approved text replacement IDs.

    Deletion removes records. A later re-add gets a new ID. Indistinguishable
    duplicate fields receive new IDs after any source change. Opaque bytes are
    never interpreted or rewritten here.
    """
    result, _ = seed_projection(document)
    if (document["source_mode"] != "imported" or previous.get("source_mode") != "imported"
            or previous.get("document_id") != document["document_id"]
            or previous.get("owner_scope") != document["owner_scope"]
            or digest(previous.get("_source", "")) != previous.get("source_sha256")):
        return result, metadata_for(result) if result["source_mode"] == "imported" else None
    old = [_record(node, previous["_source"]) for node in previous["nodes"]]
    if not all(_ID.fullmatch(record["node_id"]) for record in old):
        return result, metadata_for(result)
    if document["source_sha256"] == previous["source_sha256"]:
        bound = bind_projection(document, metadata_for(previous))
        return bound, metadata_for(bound)
    fresh = [_record(node, document["_source"]) for node in result["nodes"]]
    old_counts, new_counts = Counter(map(_signature, old)), Counter(map(_signature, fresh))
    unique_old = {_signature(record): record for record in old if old_counts[_signature(record)] == 1}
    assigned = {}
    for index, record in enumerate(fresh):
        signature = _signature(record)
        if new_counts[signature] == 1 and signature in unique_old:
            assigned[index] = unique_old[signature]["node_id"]
    if approved_patches:
        from ..resume_builder_service import resume_builder_service
        from .semantic import apply_node_edits

        expected, _ = apply_node_edits(previous, approved_patches,
                                      expected_revision=previous["content_revision"], expected_source=previous["source_sha256"])
        if expected != document["_source"]:
            raise ValueError("Approved edit mapping differs from exact source mutation")
        old_by_id = {record["node_id"]: record for record in old}
        replacements = []
        for patch in approved_patches:
            record = old_by_id[patch["node_id"]]
            raw = resume_builder_service._escape(patch["text"]) if record["encoding"] == "starter_plain" else patch["text"]
            replacements.append((record, raw))
        shift = 0
        for record, raw in sorted(replacements, key=lambda pair: pair[0]["start"]):
            start = record["start"] + shift
            end = start + len(raw)
            matches = [index for index, node in enumerate(fresh)
                       if node["start"] == start and node["end"] == end and node["raw"] == raw
                       and all(node[key] == record[key] for key in ("kind", "section", "encoding"))]
            if len(matches) == 1:
                assigned[matches[0]] = record["node_id"]
            shift += len(raw) - (record["end"] - record["start"])
    # An approved replacement may create a duplicate of an unchanged field;
    # never assign one identity to both output nodes.
    identity_counts = Counter(assigned.values())
    for index, identity in assigned.items():
        if identity_counts[identity] == 1:
            _set_identity(result["nodes"][index], identity)
    return result, metadata_for(result)
