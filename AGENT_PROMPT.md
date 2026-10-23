# Kickoff prompt for Antigravity

Put `PROJECT_GUIDE.md` and `AGENT_RULES.md` in the repo root, open the repo in Antigravity, then paste everything inside the box below as your first message. Each teammate does this in their own Antigravity window and says which person they are.

```
You are the build agent for a 12-hour hackathon project: RL-based network
slicing and resource allocation for 5G (eMBB, URLLC, mURLLC) with a live
demo UI. Two people work on this repo (Person A and Person B).

STEP 1 - READ
Read PROJECT_GUIDE.md completely, especially section 17 (phased plan,
working protocol, UX spec, ns-3 phase), then read AGENT_RULES.md.
If either file is missing, stop and tell me.

STEP 2 - CONFIRM UNDERSTANDING
Reply with a summary of at most 12 lines covering: the real-world problem,
our solution (joint radio + compute allocation, constrained RL with
Lagrangian, safety shield), the tech stack, the phases 0-8, and what is out
of scope. Then wait for me to say 'confirmed'.

STEP 3 - PHASE 0
After 'confirmed', ask me the Phase 0 environment questions from section 17
in ONE message and wait for my answers. Do not install anything before I
answer. Tell me exact commands to run for anything that needs my
permission.

HOW YOU MUST WORK
- Do ONE phase at a time. At the end of each phase: run the acceptance
  tests, show me the output, give a 5-line report and the command to run
  what you built, commit on my branch, then STOP and wait for 'next'.
- Only edit files owned by the person I tell you I am (see section 12).
- Ask me before: installing system packages, installing ns-3, changing
  config.yaml or the interface contract, adding any dependency.
- Keep everything CPU-only and laptop-friendly. No Docker, no databases.
- If a test fails twice, stop and give me the error and two options.
- ns-3 (Phase 8) is optional, time-boxed to 3 hours, and must never block
  Phases 0-7. Look up current compatible versions of ns-3, 5G-LENA and the
  Python bridge from their official repos at install time; do not use
  remembered version numbers.
- The demo must load models/agent.zip. Never train during the demo.

Begin with STEP 1 now.
```

## Per-phase prompts (send one at a time after the agent says a phase is done)

- **Next phase:** `next`
- **Retry a failure:** `Phase <n> failed test <name>. Show the error, explain the cause in 3 lines, fix it, rerun the test.`
- **Tuning the simulator (Phase 1):** `Tune config.yaml numbers so a static 60/25/15 split drops eMBB packets during an eMBB surge while URLLC stays mostly idle, but a smart split could serve everything. Show before/after numbers and ask me before saving the new config.`
- **UI review (Phase 6):** `Run the API and open the dashboard. List anything from the UX spec in section 17 that is missing, then implement it.`
- **Before demo:** `Do a full dry run: fresh clone, follow the README only, start the server, trigger all three spikes, and report anything that breaks.`
