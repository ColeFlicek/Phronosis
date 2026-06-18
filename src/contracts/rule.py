from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContractRule:
    """
    Pure representation of one contract's structural enforcement logic.
    No I/O — all methods take plain lists and return plain lists/bools.
    Extracted from ContractManager so the rule logic can be tested without a database.
    """

    prohibited_patterns: list[str]       # lower-cased callee name fragments that are forbidden
    required_callee: str | None          # if set, forbidden call is allowed when this is also called
    scope_exclusions: list[str]          # function ID prefixes exempt from checking
    missing_metadata: list[str]          # ["docstring"] triggers a PRESENCE check

    @classmethod
    def from_expr(cls, expr: dict) -> "ContractRule":
        return cls(
            prohibited_patterns=[p.lower() for p in expr.get("prohibited_patterns", [])],
            required_callee=expr.get("required_callee"),
            scope_exclusions=[s.lower() for s in expr.get("scope_exclusions", [])],
            missing_metadata=expr.get("missing_metadata", []),
        )

    def is_excluded(self, function_id: str) -> bool:
        return any(function_id.lower().startswith(ex) for ex in self.scope_exclusions)

    def excluded_names(self) -> set[str]:
        return {s.lower() for s in self.scope_exclusions}

    def find_prohibited_callees(self, callee_ids: list[str]) -> list[str]:
        """Return callee IDs that match a prohibited pattern, respecting required_callee.

        Matching priority per callee (first match wins):
        1. Glob — pattern ends with '.*': prefix match on full qualified ID
           e.g. 'src.db.*' matches 'src.db.execute', 'src.db.query'
        2. Qualified — pattern contains '.': exact match on full ID
           e.g. 'src.db.raw_query' only matches that exact function
        3. Bare name — last segment match (original behaviour, catches the common
           case but can be defeated by moving the function to a new module)
        """
        if not self.prohibited_patterns:
            return []
        if self.required_callee:
            uses_required = any(self.required_callee.lower() in c.lower() for c in callee_ids)
            if uses_required:
                return []
        hits = []
        for cid in callee_ids:
            full = cid.lower()
            last = full.split(".")[-1]
            for pattern in self.prohibited_patterns:
                matched = False
                if pattern.endswith(".*"):
                    prefix = pattern[:-2]
                    matched = full.startswith(prefix + ".") or full == prefix
                elif "." in pattern:
                    matched = full == pattern
                else:
                    matched = (last == pattern
                               or last.startswith(pattern + "_")
                               or last.endswith("_" + pattern))
                if matched:
                    hits.append(cid)
                    break
        return hits

    def needs_call_graph_check(self) -> bool:
        return bool(self.prohibited_patterns or self.required_callee)

    def needs_metadata_check(self) -> bool:
        return "docstring" in self.missing_metadata
