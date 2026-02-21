You are fixing review findings for task {task_ref}.

## Instructions

1. Get task details via ralph-tasks MCP: `tasks("{project}", {number})`
2. List open findings: `list_review_findings("{project}", {number})` — filter for status "open" in section types: {section_types}
3. For each open finding, either fix the code or decline with reason

## Fixing a Finding

If the finding is valid:
1. Fix the code as suggested
2. Call `resolve_finding(finding_id, response="description of what was fixed")`

## Declining a Finding

If the finding is incorrect or not applicable:
1. Call `decline_finding(finding_id, reason="explanation why this is not an issue")`

## Important

- Address ALL open findings in the specified section types
- Do NOT create a commit — ralph CLI handles commits
- Do NOT modify files outside the scope of the findings
- Be thorough — every open finding must be resolved or declined
