# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

SIMPLE_MEMORY_DESCRIPTION = """\
You have access to persistent memory that survives across conversation turns and helps maintain context for long-horizon tasks. Use these memory tools strategically:

**When to Use Memory:**
- **During long conversations**: Store key facts, decisions, or insights as they emerge in the current conversation
- **Technical projects**: Track implementation progress, architectural decisions, user requirements, and feedback
- **User preferences**: Save preferred approaches, coding styles, workflow patterns, or specific requirements
- **Complex problems**: Record successful strategies, solutions, or patterns for reference within the conversation
- **Multi-step tasks**: Maintain coherent state and progress across conversation turns
- **Decision points**: Document important choices made and rationale for future reference

**Memory Best Practices:**
- **Use proactively**: Update memory when key decisions are made or preferences expressed, not just at the end
- **Be strategic**: Store information that will be referenced later in the same conversation or future turns
- **Stay organized**: Structure information clearly with headers, context, and current status
- **Update regularly**: Edit memory as situations evolve rather than accumulating redundant data
- **Think ahead**: Consider what information will be valuable for upcoming parts of the conversation

Memory is session-isolated and automatically displayed in the UI for reference.
"""

READ_MEMORY_DESCRIPTION = "Read the current contents of persistent memory to review context before making decisions or continuing work"

WRITE_MEMORY_DESCRIPTION = "Store YOUR OWN planning notes and task-tracking in persistent memory (warns when overwriting existing data). Use when: (1) creating a plan or todo list for your current task, (2) after making implementation decisions during YOUR work, (3) when tracking progress or milestones, (4) when noting patterns/solutions found during execution. Do NOT use for storing user-provided documents, notes, or text — use `upload_document` for that."

EDIT_MEMORY_DESCRIPTION = "Perform targeted string replacement in memory (warns on multiple matches). Use to update existing information as situations evolve rather than accumulating redundant data"
