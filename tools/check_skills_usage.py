"""Check that BOTH local and cloud runs put skills into the prompt.

No network: both runners point at a closed port. We only inspect the
action prompt that the agent builds BEFORE the first model call.

ASCII-only on purpose: write_file truncates long lines with Cyrillic, and a
truncated check script looks exactly like a failing check.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows console is cp866/cp1251 by default, while skill descriptions hold
# characters outside it (an em dash, for one). Without this, print raises
# UnicodeEncodeError and the script dies mid-output with exit=1 - which looks
# like a logic failure although the check never reached the end.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from blackchpok_ide import skills as skills_mod  # noqa: E402
from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402

# "\u0437\u0430\u043f\u0443\u0441\u0442\u0438 \u0442\u0435\u0441\u0442\u0438" = "run the tests"
ASK = "\u0437\u0430\u043f\u0443\u0441\u0442\u0438 \u0442\u0435\u0441\u0442\u0438"
# "\u0421\u041a\u0406\u041b:" = skill header inside the prompt block
SKILL_HEADER = "\u0421\u041a\u0406\u041b:"
# "\u0421\u043a\u0456\u043b\u0438" = "skills"
SKILLS_WORD = "\u0421\u043a\u0456\u043b\u0438"


def build(model: str) -> AgentRunner:
    runner = AgentRunner(
        ToolRegistry(ROOT),
        LLMSettings(base_url="http://127.0.0.1:9/v1", model=model, timeout=2),
        AgentSettings(offline_fallback=False),
        ROOT,
    )
    runner.skill_book = skills_mod.SkillBook(ROOT)
    runner.settings_ref = None
    return runner


def main() -> int:
    book = skills_mod.SkillBook(ROOT)
    print("skills found:", len(book.skills))
    for skill in book.skills:
        print("  -", skill.name, "|", skill.description[:60])

    chosen = book.auto_enable(ASK)
    print("\nauto_enable ->", [skill.name for skill in chosen])
    block = book.prompt()
    print("prompt block chars:", len(block))
    print("prompt has skill header:", SKILL_HEADER in block)

    for label, model in (("local", "qwen2.5-coder"),
                         ("cloud", "deepseek-chat")):
        runner = build(model)
        names = {schema["function"]["name"] for schema in runner.tool_schemas()}
        started = runner.start(ASK)
        prompt = runner.session.action_prompt
        print("\n[" + label + "] started:", started)
        print("  use_skills:", runner.agent_settings.use_skills)
        print("  has list_skills/read_skill:",
              {"list_skills", "read_skill"} <= names)
        print("  action_prompt chars:", len(prompt))
        print("  skill instructions in prompt:",
              SKILL_HEADER in prompt or SKILLS_WORD in prompt)
        runner.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
