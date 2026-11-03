#!/bin/bash
# skills.sh - AI Agent Utility Dispatcher
# This script acts as an entry point for AI Coding Agents to execute predefined "skills".
# Think of it as a local CLI designed for agents.

set -e

SKILLS_DIR="./skills"

# Ensure skills directory exists
if [ ! -d "$SKILLS_DIR" ]; then
    echo "Error: $SKILLS_DIR directory not found."
    exit 1
fi

print_usage() {
    echo "Usage: ./skills.sh <skill_name> [args...]"
    echo ""
    echo "Available skills:"
    # List all executable files in the skills directory recursively, excluding directories
    find "$SKILLS_DIR" -type f -executable | sed "s|^\./skills/||" | awk '{print "  - "$1}'
}

if [ $# -eq 0 ]; then
    print_usage
    exit 1
fi

SKILL_NAME=$1
shift # Remove the first argument so $@ contains only the arguments for the skill

SKILL_PATH="$SKILLS_DIR/$SKILL_NAME"

if [ ! -x "$SKILL_PATH" ]; then
    echo "Error: Skill '$SKILL_NAME' not found or is not executable."
    echo "Looking for: $SKILL_PATH"
    echo ""
    print_usage
    exit 1
fi

# Execute the specific skill
echo "Executing AI Skill: $SKILL_NAME"
"$SKILL_PATH" "$@"
