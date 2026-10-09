# RQ-03 live qualification protected ingress

Authority inputs are read only from the Owner-pinned trust-anchor commit materialized outside the candidate run root. Candidate/run-directory files never select the authority profile, policy epoch, controller allowlist, role grants, or protected operation index. Operation-index changes are proposed by the qualification task but become authoritative only after an Owner-controlled append commit. Existing entries are append-only and may not be rewritten or removed.
