from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_CORE_COMPONENT_LINES = 3_000
CORE_COMPONENTS = (
    PROJECT_ROOT / "src/app/components/WeeklyReport.tsx",
    PROJECT_ROOT / "src/app/components/SelfAnalysis.tsx",
    PROJECT_ROOT / "src/app/components/SystemSettings.tsx",
)


def main() -> None:
    oversized: list[str] = []
    for path in CORE_COMPONENTS:
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"{path.relative_to(PROJECT_ROOT)}: {line_count} lines")
        if line_count > MAX_CORE_COMPONENT_LINES:
            oversized.append(f"{path.name}={line_count}")
    if oversized:
        raise SystemExit(
            "Core component size gate failed (limit 3000): " + ", ".join(oversized)
        )


if __name__ == "__main__":
    main()
