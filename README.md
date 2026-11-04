<img src="assets/icon.svg" width="64" height="64" alt="">

# t3 code to linear

Lets people in Linear assign or @mention a T3 Code agent on an issue. T3 picks it up, works in a new worktree, and reports back on the issue.

- `SPEC.md`: how it works and why
- `docs/setup.md`: connecting a Linear workspace to a T3 server
- `docs/task-prompt.md`: the prompt for the T3 webhook task
- `bin/linear`, `bin/t3-dispatch`: the scripts the agents run
- `eval/`: the grader that picked the dispatcher model (`python3 -I eval/grade.py`, then `python3 -I eval/chart.py` for `eval/report.html`)

Created in [T3 Code](https://t3.codes).
