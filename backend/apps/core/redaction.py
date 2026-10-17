"""Deterministic partial responses (authorization model for D1/D2/D6).

Two checks guard every aggregate read endpoint: property scope (the property
is one the caller can see) and an entry permission. Inside a response, each
group of fields that belongs to another module is gated by that module's own
permission. A group the caller can't see is returned as `null` and its name
is listed in a top-level `redacted` array — never a 403, which is reserved
for having no entry permission at all. A `null` that is *not* listed in
`redacted` simply means "no data".
"""
from .roles import permissions_for_user


class Redactor:
    def __init__(self, user):
        self.permissions = set(permissions_for_user(user))
        self.redacted = []

    def allows(self, *codes):
        """True when the caller holds every code (derived metrics need every
        constituent permission)."""
        return set(codes) <= self.permissions

    def group(self, name, codes, build):
        """`build()` when allowed, else None and `name` is recorded as redacted.
        `build` is a callable so withheld data is never even queried."""
        if self.allows(*codes):
            return build()
        if name not in self.redacted:
            self.redacted.append(name)
        return None
