# Agent rules (read before every task)

1. Read `PROJECT_GUIDE.md` fully before coding. If something is ambiguous, ask instead of guessing.
2. Work on one phase at a time (section 17). After each phase: run its acceptance tests, report, commit, then stop and wait for 'next'.
3. Edit only the files owned by the person who invoked you (section 12). Never rewrite unrelated files.
4. Do not add dependencies, change `config.yaml`, or change the interface contract (section 6) without asking.
5. Ask before installing anything on the system, and before installing ns-3.
6. Keep everything laptop-friendly: CPU only, no Docker, no heavy services.
7. If an acceptance test fails twice, stop and report the error with two options. Do not keep looping.
8. Keep functions small, with type hints and short docstrings. No hidden global state.
9. Never train live in the demo. Always load `models/agent.zip`.
10. Show a `git diff` summary before committing. Use branches `a/<topic>` or `b/<topic>`, never commit to `main` directly.
11. ns-3 is optional and time-boxed. It must never block the Python demo.
