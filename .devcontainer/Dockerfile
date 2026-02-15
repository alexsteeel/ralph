# Project-specific Dockerfile
# Extends the AI Agents Sandbox devcontainer image

FROM ai-agents-sandbox/devcontainer:1.1.2

# Switch to root for any additional installations
USER root

# Add any project-specific system packages here
# RUN apt-get update && apt-get install -y \
#     package1 \
#     package2 \
#     && rm -rf /var/lib/apt/lists/*

# Switch back to claude user
USER claude

# Add any project-specific user packages here
# RUN pip install --user package1 package2
# RUN npm install -g package1 package2

# Copy any project-specific configuration
# COPY --chown=claude:local-ai-team ./configs /home/claude/.config

WORKDIR /workspace