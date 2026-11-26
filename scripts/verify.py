"""Run offline acceptance tests with only Python + Node, from any cwd."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    for part in ["contracts", "markets", "server", "integration"]:
        for f in (ROOT / "src" / part).glob("*.py"):
            tree = ast.parse(f.read_text())
            banned = (
                {"src.markets", "src.server"}
                if part == "contracts"
                else {"src.server" if part == "markets" else "src.markets"}
            )
            imports = {
                a.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for a in node.names
            } | {
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            }
            if any(m == b or m.startswith(b + ".") for m in imports for b in banned):
                raise RuntimeError("Illegal dependency: " + str(f))
        run(sys.executable, "-m", "unittest", "discover", "-s", "tests/" + part)
    for m in (ROOT / "src/ui").glob("*.mjs"):
        run("node", "--check", str(m))
    run("node", "--test", "tests/ui/screen.test.mjs")
    print("PASS server, feed, calculations, HTTP, UI models and import boundaries.")


if __name__ == "__main__":
    main()
