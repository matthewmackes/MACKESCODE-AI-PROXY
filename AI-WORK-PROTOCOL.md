# AI WORK PROTOCOL - MDE LLM-PROXY

## Quick Reference for All AI Assistants

### BEFORE Starting Work:
1. **READ** `GOVERNANCE.md` for architectural locks and definition of done.
2. **CHECK** `MAIN-WORKLIST.md`, `docs/requirements-ledger.md`, and `docs/NEEDS-OPERATOR.md`.
3. **CLAIM** existing tracked work when appropriate, or add a scoped task if the work is not represented.
4. **DOCUMENT** start time, scope, and verification plan for non-trivial work.

### DURING Work:
1. **UPDATE** Progress Notes with timestamps
2. **COMMIT** regularly with clear messages
3. **TEST** changes as you go
4. **DOCUMENT** any issues or blockers

### AFTER Completing Work:
1. **UPDATE** Status to COMPLETED or NEEDS_REVIEW
2. **ADD** completion timestamp
3. **VERIFY** all completion criteria met
4. **UPDATE** related documentation
5. **RUN** final verification tests and record any skipped evidence

## Task Status Updates:
- `TODO` → `IN_PROGRESS` (when starting)
- `IN_PROGRESS` → `COMPLETED` (when done)
- `IN_PROGRESS` → `BLOCKED` (if stuck)
- `COMPLETED` → `NEEDS_REVIEW` (if review needed)

## Commit Message Format:
```
[Task-ID] Brief description of changes

- Specific change 1
- Specific change 2
- Related documentation updated

Closes: #related-issue (if applicable)
Co-Authored-By: Claude <noreply@anthropic.com>
```

## Priority Guidance:
- **P0**: Drop everything and work on this
- **P1**: Work on this before P2/P3 tasks
- **P2**: Work on after P1 tasks complete
- **P3**: Future enhancements, lowest priority

## Quality Standards:
1. **Tests Required**: All changes need tests
2. **Documentation**: Update docs when behavior, workflows, governance, security posture, or release process changes
3. **Backward Compatibility**: Don't break existing functionality
4. **Security**: Consider security implications
5. **Performance**: Monitor for regressions
6. **Runtime Reachability**: No dead UI controls, placeholder workflows, or documented-only features

## Communication Protocol:
- Update MAIN-WORKLIST.md with progress
- Use clear, descriptive notes
- Include timestamps for all updates
- Document decisions and rationale

## Emergency Procedures:
If you encounter:
- **Security vulnerability**: Stop work and document immediately
- **Breaking change**: Flag for review before merging
- **Performance regression**: Investigate before proceeding
- **Blocked by live resource/operator decision**: Add or update `docs/NEEDS-OPERATOR.md`

## Verification Checklist (Before Marking COMPLETED):
- [ ] All completion criteria met
- [ ] Tests pass
- [ ] Documentation updated
- [ ] No linting errors
- [ ] Performance acceptable
- [ ] Security review complete
- [ ] Backward compatibility verified

---

## Current Active Tasks

Check `MAIN-WORKLIST.md`. Do not trust old active-task lists copied into chat or
stale docs. If a task cannot be closed without DigitalOcean capacity, billing
visibility, a token, GitHub administration, or another operator choice, record it
in `docs/NEEDS-OPERATOR.md`.

## Key Files to Know:
- `MAIN-WORKLIST.md` - Work tracking (READ FIRST)
- `GOVERNANCE.md` - Architectural locks and definition of done
- `CLAUDE.md` - Project instructions
- `docs/DECISIONS.md` - Append-only decision log
- `docs/NEEDS-OPERATOR.md` - Live-resource/operator blockers
- `docs/THREAT_MODEL.md` - Security model
- `image-studio.py` - Current unified console
- `do-anthropic-proxy.py` - API proxy server
- `claude-DO.sh` - Main launcher script

## Testing Commands:
```bash
# Quick smoke test
python3 image-studio.py --no-open &
curl http://localhost:18181/health

# Proxy test
curl http://127.0.0.1:18081/v1/models
```

**Remember:** The work is not done until it is runtime-reachable, verified, and
the relevant docs or ledgers are current.
**Last Updated:** 2026-07-09
**By:** Codex
