from importlib.resources import files


def load_prompt(name: str) -> str:
    return files("japan_reader.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
