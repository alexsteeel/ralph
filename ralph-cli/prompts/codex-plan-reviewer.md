Review the plan for task {project}#{number}.

1. Read the task using MCP tool: tasks("{project}", {number})
2. Compare the plan against the body (requirements). Check:
   - Completeness: does the plan cover ALL requirements from the body?
   - Scope correctness: do referenced files/functions exist?
   - Implementation steps: are they realistic and in the right order?
   - Testing strategy: is it adequate for the changes?
   - Missing edge cases
3. Print your findings as a structured list. For each issue state severity (CRITICAL/MEDIUM/LOW) and description.
4. If no issues found, print "LGTM — plan covers all requirements."
5. Do NOT modify any files or call any MCP tools besides reading the task.
