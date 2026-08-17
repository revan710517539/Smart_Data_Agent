from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_COMPONENTS = {
    # Weekly report and intelligent analysis gained the governed page-data and
    # visualization workbenches. Keep a narrow release ceiling while the next
    # extraction moves those orchestration branches into dedicated modules.
    PROJECT_ROOT / "src/app/components/WeeklyReport.tsx": 3_100,
    PROJECT_ROOT / "src/app/components/SelfAnalysis.tsx": 3_100,
    PROJECT_ROOT / "src/app/components/SystemSettings.tsx": 3_000,
}


def main() -> None:
    oversized: list[str] = []
    for path, limit in CORE_COMPONENTS.items():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"{path.relative_to(PROJECT_ROOT)}: {line_count}/{limit} lines")
        if line_count > limit:
            oversized.append(f"{path.name}={line_count}>{limit}")
    if oversized:
        raise SystemExit("Core component size gate failed: " + ", ".join(oversized))


if __name__ == "__main__":
    main()
