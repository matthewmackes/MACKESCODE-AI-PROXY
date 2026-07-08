# AI WORK PROTOCOL - Matts Value Set Proxy

## Quick Reference for All AI Assistants

### BEFORE Starting Work:
1. **READ** MAIN-WORKLIST.md completely
2. **CHECK** if task already exists or is in progress
3. **CLAIM** task by updating Assigned To and Status
4. **DOCUMENT** start time and estimated duration

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
5. **RUN** final verification tests

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
2. **Documentation**: Update CLAUDE.md, README.md
3. **Backward Compatibility**: Don't break existing functionality
4. **Security**: Consider security implications
5. **Performance**: Monitor for regressions

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
- **Blocked by dependency**: Update status to BLOCKED

## Verification Checklist (Before Marking COMPLETED):
- [ ] All completion criteria met
- [ ] Tests pass
- [ ] Documentation updated
- [ ] No linting errors
- [ ] Performance acceptable
- [ ] Security review complete
- [ ] Backward compatibility verified

---

## Current Active Tasks (Check MAIN-WORKLIST.md):
- INT-006: Early health check endpoints (P1)
- INT-002: HTTP handler refactoring (P1)
- INT-015: Digital Ocean Serverless Inference model catalog (P1)
- INT-016: DigitalOcean Dedicated Inference lifecycle manager (P1)
- INT-017: Model Hero Card descriptions (P1)
- INT-003: Error handling improvements (P1)
- INT-004: Configuration system (P1)
- INT-005: Comprehensive test suite (P1)

## Key Files to Know:
- `MAIN-WORKLIST.md` - Work tracking (READ FIRST)
- `CLAUDE.md` - Project instructions
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

**Remember:** Always update MAIN-WORKLIST.md before, during, and after work!  
**Last Updated:** 2026-07-07  
**By:** Codex