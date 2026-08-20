# Blackwell pulse test fixtures

**TEST-ONLY — NOT PRODUCTION EVIDENCE.**

`cases.json` enumerates the valid, missing, incompatible, and tampered fixture states.
`tests/test_blackwell_pulse.py` generates byte-stable upstream release bundles in
temporary directories from that contract. Every generated claim summary, publisher,
synthetic range, release tag, and asset name is explicitly marked test-only.

Small fixtures isolate classification behavior. Release-writer fixtures exercise the full
frozen synthetic-input audit and categorical gate surface using generated test-only claim
values. Neither family is an Atlas release or evidence, and neither may be copied into a
production lockfile.
