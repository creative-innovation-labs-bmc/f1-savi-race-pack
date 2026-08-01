# Working rules

- Read `PROJECT_BRIEF.md` before changing the project.
- Use Australian English for user-facing copy.
- Do not commit credentials, session cookies or tokens.
- Treat the cumulative FantasyGP standings as authoritative. Do not assume they equal the simple sum of race columns because FantasyGP can apply corrections.
- Preserve competition ranking for ties: tied entries share a position and the following position is skipped.
- Run `python -m unittest discover -s tests -v` before committing.
- Build and verify the Hungary Round 11 reference pack after changes.
- Never replace a previously valid race pack when validation fails.
