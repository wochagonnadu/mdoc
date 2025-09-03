import argparse
import os
import sys
import sys
import json
import ast
import importlib.util
from pathlib import Path

# For gitignore parsing
try:
    import pathspec
    _HAVE_PATHSPEC = True
except Exception:
    pathspec = None
    _HAVE_PATHSPEC = False
    # Minimal fallback stub: matches nothing (i.e., behave as if no gitignore)
    class _NoPathSpec:
        @staticmethod
        def from_lines(patterns, lines):
            return _NoPathSpec()

        def match_file(self, path):
            return False

    pathspec = _NoPathSpec

IGNORE_DIRS = {'__pycache__', '.git', '.idea', 'node_modules'}
CODE_EXTS = {'.py', '.md', '.json', '.yml', '.yaml', '.toml', '.ini'}
DEFAULT_MAX_BYTES = 50 * 1024  # 50 KB


# --- Gitignore support ---
def load_gitignore_patterns(root):
    """Load .gitignore patterns from root directory, return PathSpec or None."""
    gitignore_file = Path(root) / '.gitignore'
    if gitignore_file.exists():
        with open(gitignore_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, lines)
    return None

def is_leaf_dir(path):
    """Return True if path is a directory and has no subdirectories (except ignored ones)."""
    if not path.is_dir():
        return False
    for child in path.iterdir():
        if child.is_dir() and child.name not in IGNORE_DIRS:
            return False
    return True

def find_leaf_dirs(root, gitignore_spec=None):
    """Yield all leaf directories under root, skipping ignored by gitignore_spec."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Remove ignored dirs in-place
        abs_dir = Path(dirpath)
        # Remove ignored dirs (by IGNORE_DIRS and gitignore)
        new_dirnames = []
        for d in dirnames:
            if d in IGNORE_DIRS:
                continue
            full_path = abs_dir / d
            rel_path = os.path.relpath(full_path, root)
            if gitignore_spec and gitignore_spec.match_file(rel_path):
                continue
            new_dirnames.append(d)
        dirnames[:] = new_dirnames
        # Check if leaf
        if not dirnames:
            yield abs_dir

def get_code_files(path, gitignore_spec=None, root=None):
    """Return list of Path objects for code files in path (non-recursive), skipping gitignored."""
    files = []
    for p in path.iterdir():
        if not p.is_file():
            continue
        if p.suffix not in CODE_EXTS:
            continue
        rel_path = os.path.relpath(p, root if root else path)
        if gitignore_spec and gitignore_spec.match_file(rel_path):
            continue
        files.append(p)
    return files

def file_tree_str(path, prefix=''):
    """Return a string representing the file tree under path (one level)."""
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = []
    for entry in entries:
        if entry.name in IGNORE_DIRS:
            continue
        if entry.is_dir():
            lines.append(f"{prefix}{entry.name}/")
        else:
            lines.append(f"{prefix}{entry.name}")
    return '\n'.join(lines)

def parse_python_file(filepath):
    """Parse a python file and extract public functions, classes, their docstrings, and __all__."""
    public_api = []
    all_list = None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(filepath))
    except Exception:
        return public_api, all_list

    # Find __all__ if present
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__':
                    try:
                        # Evaluate __all__ value if it's a list of strings
                        all_list = []
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Str):
                                    all_list.append(elt.s)
                    except Exception:
                        all_list = None
                    break
        if all_list is not None:
            break

    # Extract public functions and classes
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if not node.name.startswith('_'):
                doc = ast.get_docstring(node)
                first_line = doc.splitlines()[0] if doc else ''
                public_api.append({'name': node.name, 'type': 'function', 'doc': first_line})
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith('_'):
                doc = ast.get_docstring(node)
                first_line = doc.splitlines()[0] if doc else ''
                public_api.append({'name': node.name, 'type': 'class', 'doc': first_line})

    # If __all__ is defined, filter public_api to only those names
    if all_list is not None:
        filtered_api = []
        for item in public_api:
            if item['name'] in all_list:
                filtered_api.append(item)
        public_api = filtered_api

    return public_api, all_list

def find_imports(filepath):
    """Parse a python file and extract imported modules."""
    imports = set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(filepath))
    except Exception:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def is_standard_lib(module_name):
    """Check if a module is a standard library module."""
    if module_name in sys.builtin_module_names:
        return True
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            return False
        # Check if the origin path is inside the standard library path
        std_lib_paths = [os.path.normcase(p) for p in sys.path if 'site-packages' not in p and 'dist-packages' not in p]
        origin_path = os.path.normcase(spec.origin)
        return any(origin_path.startswith(p) for p in std_lib_paths)
    except Exception:
        return False

def find_config_files(path):
    """Find configuration files in the directory."""
    config_files = []
    for ext in ['.yml', '.yaml', '.ini', '.toml', '.json']:
        for f in path.glob(f'*{ext}'):
            if f.is_file():
                config_files.append(f.name)
    return config_files

def find_env_vars(path):
    """Find variables in .env file in the directory."""
    env_vars = []
    env_path = path / '.env'
    if env_path.exists() and env_path.is_file():
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        var = line.split('=', 1)[0].strip()
                        env_vars.append(var)
        except Exception:
            pass
    return env_vars

def dump_module(path, max_bytes, dry_run=False, verbose=False, gitignore_spec=None, root=None):
    """Create module_dump.md and README.generated.md for a leaf dir."""
    code_files = get_code_files(path, gitignore_spec=gitignore_spec, root=root)
    total_bytes = 0
    module_dump_lines = []
    module_dump_lines.append(f"# File tree of `{path.name}`\n")
    module_dump_lines.append("```tree\n" + file_tree_str(path) + "\n```\n")
    module_dump_lines.append(f"# File contents (up to {max_bytes} bytes)\n")
    for f in code_files:
        if total_bytes >= max_bytes:
            module_dump_lines.append(f"\n...Content truncated at {max_bytes} bytes total.\n")
            break
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fin:
                content = fin.read()
        except Exception as e:
            content = f"[Error reading file: {e}]"
        content_bytes = len(content.encode('utf-8'))
        if total_bytes + content_bytes > max_bytes:
            allowed = max_bytes - total_bytes
            content = content.encode('utf-8')[:allowed].decode('utf-8', errors='replace')
            content_bytes = len(content.encode('utf-8'))
        module_dump_lines.append(f"\n## `{f.name}`\n")
        module_dump_lines.append("```{}\n".format(f.suffix.lstrip('.')))
        module_dump_lines.append(content)
        module_dump_lines.append("```\n")
        total_bytes += content_bytes
    module_dump = '\n'.join(module_dump_lines)
    dump_path = path / "module_dump.md"
    if verbose:
        print(f"[INFO] Writing {dump_path} ({total_bytes} bytes)")
    if not dry_run:
        with open(dump_path, "w", encoding="utf-8") as fout:
            fout.write(module_dump)

    # Analyze python files to extract public API and dependencies
    public_api_items = []
    all_public_names = set()
    imports_all = set()
    for f in code_files:
        if f.suffix == '.py':
            api, all_list = parse_python_file(f)
            public_api_items.extend(api)
            if all_list is not None:
                all_public_names.update(all_list)
            imports = find_imports(f)
            imports_all.update(imports)

    # If __all__ defined in any file, filter public_api_items accordingly
    if all_public_names:
        public_api_items = [item for item in public_api_items if item['name'] in all_public_names]

    # Determine internal and external dependencies
    internal_deps = set()
    external_deps = set()
    project_root_name = path.parts[0] if len(path.parts) > 0 else ''
    for mod in imports_all:
        if mod == '' or mod is None:
            continue
        if mod == project_root_name or (project_root_name and mod.startswith(project_root_name)):
            internal_deps.add(mod)
        elif is_standard_lib(mod):
            continue
        else:
            external_deps.add(mod)

    # Find config files and env variables
    config_files = find_config_files(path)
    env_vars = find_env_vars(path)

    # Find tests info
    test_files = [f.name for f in code_files if f.name.startswith('test_') or f.name.endswith('_test.py')]
    has_tests_dir = (path / 'tests').is_dir()
    tests_info = 'N/A'
    if test_files or has_tests_dir:
        tests_list = []
        if has_tests_dir:
            tests_list.append('tests/ directory present')
        if test_files:
            tests_list.append('Test files: ' + ', '.join(test_files))
        tests_info = '\n'.join(tests_list)

    # Prepare YAML block with gathered info
    yaml_dict = {
        'module': path.name,
        'owner': 'wochagonnadu',
        'audience': 'developer',
        'purpose': '',
        'public_api': [item['name'] for item in public_api_items] if public_api_items else [],
        'inputs': [],
        'outputs': [],
        'config': {
            'env': env_vars if env_vars else [],
            'files': config_files if config_files else [],
        },
        'deps': {
            'internal': sorted(list(internal_deps)) if internal_deps else [],
            'external': sorted(list(external_deps)) if external_deps else [],
        },
        'invariants': [],
        'danger_zones': [],
    }
    json_block = "---\n" + json.dumps(yaml_dict, indent=2, ensure_ascii=False) + "\n---\n"

    # Prepare public interfaces table
    if public_api_items:
        table_lines = ["| Имя | Тип | Описание |", "| --- | --- | --- |"]
        for item in public_api_items:
            name = item['name']
            typ = item['type']
            desc = item['doc'] if item['doc'] else 'N/A'
            # Escape pipe characters in description
            desc = desc.replace('|', '\\|')
            table_lines.append(f"| {name} | {typ} | {desc} |")
        public_interfaces_section = "# 3. Публичные интерфейсы\n\n" + '\n'.join(table_lines) + "\n"
    else:
        public_interfaces_section = "# 3. Публичные интерфейсы\n\nN/A\n"

    # Prepare other sections
    sections = [
        "# 1. Название\n\nN/A\n",
        "# 2. Ответственность\n\nN/A\n",
        public_interfaces_section,
        "# 4. Зависимости\n\nN/A\n",
        "# 5. Конфигурация\n\nN/A\n",
        f"# 6. Запуск и тесты\n\n{tests_info}\n",
        "# 7. Поток данных (Mermaid)\n\n```mermaid\ngraph TD\n    N/A\n```\n",
        "# 8. Инварианты\n\nN/A\n",
        "# 9. Опасные зоны\n\nN/A\n"
    ]
    readme_content = json_block + '\n'.join(sections)
    readme_path = path / "README.generated.md"
    if verbose:
        print(f"[INFO] Writing {readme_path}")
    if not dry_run:
        with open(readme_path, "w", encoding="utf-8") as fout:
            fout.write(readme_content)

def aggregate_readmes(parent_path, dry_run=False, verbose=False):
    """Aggregate README files from subdirectories into module_aggregated.md.

    Behavior:
    - Scans immediate subdirectories of `parent_path` (excluding IGNORE_DIRS).
    - Includes content from `README.generated.md` if present.
    - Also includes content from handwritten `README.md` if present.
    - Writes combined raw material to `module_aggregated.md`.
    - If no inputs found, writes a short explanatory stub instead of an empty file.
    - Additionally, creates `README.aggregated.md` scaffold if it doesn't exist
      (left for LLM/human to curate using module_aggregated.md as source).
    """
    parent = Path(parent_path)
    aggregated_lines = []
    for child in sorted(parent.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in IGNORE_DIRS:
            continue
        readme_generated = child / "README.generated.md"
        readme_manual = child / "README.md"

        block_added = False
        if readme_generated.exists():
            aggregated_lines.append(f"# {child.name}\n")
            aggregated_lines.append(f"> Source: {readme_generated.relative_to(parent)}\n\n")
            with open(readme_generated, "r", encoding="utf-8") as fin:
                aggregated_lines.append(fin.read())
            aggregated_lines.append("\n")
            block_added = True
            if verbose:
                print(f"[INFO] Aggregated {readme_generated}")

        if readme_manual.exists():
            # Include manual README as an additional block
            if not block_added:
                aggregated_lines.append(f"# {child.name}\n")
            aggregated_lines.append(f"> Source: {readme_manual.relative_to(parent)}\n\n")
            try:
                with open(readme_manual, "r", encoding="utf-8") as fin:
                    aggregated_lines.append(fin.read())
            except Exception as e:
                aggregated_lines.append(f"[Error reading {readme_manual.name}: {e}]\n")
            aggregated_lines.append("\n")
            if verbose:
                print(f"[INFO] Aggregated {readme_manual}")

    # Write module_aggregated.md
    agg_path = parent / "module_aggregated.md"
    if verbose:
        print(f"[INFO] Writing {agg_path}")
    if not dry_run:
        with open(agg_path, "w", encoding="utf-8") as fout:
            if aggregated_lines:
                fout.write('\n'.join(aggregated_lines))
            else:
                fout.write(
                    "# Aggregated Module Docs\n\n"
                    "No child README files found. Run `mdoc dump-leaves` in the project first,\n"
                    "or add README.md files to child modules.\n"
                )

    # Create README.aggregated.md scaffold if missing
    readme_agg_path = parent / "README.aggregated.md"
    if not dry_run and not readme_agg_path.exists():
        if verbose:
            print(f"[INFO] Creating scaffold {readme_agg_path}")
        scaffold = (
            "# README.aggregated.md\n\n"
            "Этот файл предназначен для сводного человеческого/LLM-описания модуля на основе\n"
            "сырых материалов из `module_aggregated.md`.\n\n"
            "Подсказка: откройте `module_aggregated.md` и создайте здесь краткую, структурированную\n"
            "версию (цель, содержание, ключевые интерфейсы, зависимости, запуск).\n"
        )
        with open(readme_agg_path, "w", encoding="utf-8") as fout:
            fout.write(scaffold)

def do_dump_leaves(root, max_bytes, dry_run, verbose, gitignore_spec):
    """Logic for the dump-leaves command."""
    for leaf in find_leaf_dirs(root, gitignore_spec=gitignore_spec):
        if verbose:
            print(f"[INFO] Leaf dir: {leaf}")
        dump_module(leaf, max_bytes, dry_run=dry_run, verbose=verbose, gitignore_spec=gitignore_spec, root=root)

def do_aggregate_all(root, dry_run, verbose, gitignore_spec):
    """Logic for bottom-up aggregation."""
    all_dirs = []
    for dirpath, dirnames, _ in os.walk(root):
        # Filter out ignored directories
        new_dirnames = []
        for d in dirnames:
            if d in IGNORE_DIRS:
                continue
            full_path = Path(dirpath) / d
            rel_path = os.path.relpath(full_path, root)
            if gitignore_spec and gitignore_spec.match_file(rel_path):
                continue
            new_dirnames.append(d)
        dirnames[:] = new_dirnames
        all_dirs.append(Path(dirpath))

    # Sort directories by depth, deepest first
    sorted_dirs = sorted(all_dirs, key=lambda p: len(p.parts), reverse=True)

    for d in sorted_dirs:
        aggregate_readmes(d, dry_run=dry_run, verbose=verbose)

def main():
    parser = argparse.ArgumentParser(description="Module documentation CLI")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # --- dump-leaves command ---
    dump_parser = subparsers.add_parser('dump-leaves', help="Generate docs for all leaf directories under PATH")
    dump_parser.add_argument('path', type=str, help="Root path to search for leaf directories")
    dump_parser.add_argument('--dry-run', action='store_true', help="Don't write files")
    dump_parser.add_argument('--verbose', action='store_true', help="Print extra info")
    dump_parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES, help="Max bytes of file content per module (default 50KB)")

    # --- aggregate command ---
    agg_parser = subparsers.add_parser('aggregate', help="Aggregate README.generated.md in subdirs under PATH")
    agg_parser.add_argument('path', type=str, help="Parent path containing module dirs")
    agg_parser.add_argument('--dry-run', action='store_true', help="Don't write files")
    agg_parser.add_argument('--verbose', action='store_true', help="Print extra info")

    # --- full-run command ---
    full_run_parser = subparsers.add_parser('full-run', help="Run dump-leaves and then aggregate for the entire project.")
    full_run_parser.add_argument('path', type=str, help="Root path of the project")
    full_run_parser.add_argument('--dry-run', action='store_true', help="Don't write files")
    full_run_parser.add_argument('--verbose', action='store_true', help="Print extra info")
    full_run_parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES, help="Max bytes for dump-leaves (default 50KB)")

    args = parser.parse_args()

    root = Path(args.path)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    gitignore_spec = load_gitignore_patterns(root)

    if args.command == 'dump-leaves':
        do_dump_leaves(root, args.max_bytes, args.dry_run, args.verbose, gitignore_spec)

    elif args.command == 'aggregate':
        aggregate_readmes(root, dry_run=args.dry_run, verbose=args.verbose)

    elif args.command == 'full-run':
        print("-- Running dump-leaves phase --")
        do_dump_leaves(root, args.max_bytes, args.dry_run, args.verbose, gitignore_spec)
        print("\n-- Running aggregation phase (bottom-up) --")
        do_aggregate_all(root, args.dry_run, args.verbose, gitignore_spec)

if __name__ == "__main__":
    main()
