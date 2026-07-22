import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+])?==([^\s;]+)$")


def main() -> int:
    requirements_path = Path(__file__).with_name("requirements.txt")
    failures = []
    checked = 0
    for line_number, raw_line in enumerate(requirements_path.read_text(encoding="utf-8").splitlines(), start=1):
        requirement = raw_line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        match = REQUIREMENT_RE.fullmatch(requirement)
        if not match:
            failures.append(f"line {line_number}: unsupported requirement format: {requirement}")
            continue
        package_name, expected_version = match.groups()
        checked += 1
        try:
            installed_version = version(package_name)
        except PackageNotFoundError:
            failures.append(f"{package_name}: missing (expected {expected_version})")
            continue
        if installed_version != expected_version:
            failures.append(f"{package_name}: installed {installed_version}, expected {expected_version}")

    if failures:
        print("Locked dependency check: FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"Locked dependency check: PASSED ({checked} requirements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
