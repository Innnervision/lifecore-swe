"""File editor restricted to repository boundary."""

from pathlib import Path


class RepositoryEditor:
    """Modifies file contents within repository boundary."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def write_file(self, rel_path: str, content: str) -> None:
        """Write content to file inside repository with path containment check."""
        target_path = (self.repo_path / rel_path).resolve()
        if not str(target_path).startswith(str(self.repo_path)):
            raise PermissionError(f"Access denied: Path {rel_path} escapes repository boundary.")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

    def replace_in_file(self, rel_path: str, old_str: str, new_str: str) -> bool:
        """Replace occurrences of old_str with new_str in file with normalization fallbacks."""
        target_path = (self.repo_path / rel_path).resolve()
        if not str(target_path).startswith(str(self.repo_path)):
            raise PermissionError(f"Access denied: Path {rel_path} escapes repository boundary.")
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Direct match
        if old_str in content:
            updated_content = content.replace(old_str, new_str, 1)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(updated_content)
            return True

        # Normalized newline match
        norm_content = content.replace("\r\n", "\n")
        norm_old = old_str.replace("\r\n", "\n")
        if norm_old in norm_content:
            updated_content = norm_content.replace(norm_old, new_str.replace("\r\n", "\n"), 1)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(updated_content)
            return True

        # Line-by-line stripped match fallback
        old_lines = [l.strip() for l in norm_old.splitlines() if l.strip()]
        if len(old_lines) == 1:
            target_line = old_lines[0]
            lines = norm_content.splitlines(keepends=True)
            for idx, line in enumerate(lines):
                if target_line in line:
                    # Preserve leading indentation
                    indent = line[: len(line) - len(line.lstrip())]
                    lines[idx] = f"{indent}{new_str.strip()}\n"
                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write("".join(lines))
                    return True

        return False
