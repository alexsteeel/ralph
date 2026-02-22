Review the plan for task {project}#{number}.

1. Read the task using MCP tool: tasks("{project}", {number})
2. Compare the plan against the body (requirements). Check:
   - Completeness: does the plan cover ALL requirements from the body?
   - Scope correctness: do referenced files/functions exist?
   - Implementation steps: are they realistic and in the right order?
   - Testing strategy: is it adequate for the changes?
   - Missing edge cases
3. For each issue found, call:
   add_review_finding(
     project="{project}",
     number={number},
     review_type="plan",
     text="<description of the issue>",
     author="codex-plan-reviewer"
   )
4. If no issues found, do NOT create any findings.
5. Do NOT modify any files.
