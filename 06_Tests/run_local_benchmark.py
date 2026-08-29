"""生成可重复的异常检测基准结果，输出到 07_Logs。"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "02_Source" / "agent_tech_portfolio"
sys.path.insert(0, str(SOURCE))

from aiops_agent import Alert, MonitorAgent


def main() -> int:
    rng = random.Random(20260829)
    monitor = MonitorAgent()
    rows: list[tuple[bool, bool]] = []
    for _ in range(200):
        baseline = [rng.gauss(50, 3) for _ in range(24)]
        value = rng.gauss(50, 3)
        rows.append((False, monitor.confirm(Alert("benchmark", "cpu", value, baseline))["confirmed"]))
    for _ in range(40):
        baseline = [rng.gauss(50, 3) for _ in range(24)]
        value = rng.gauss(90, 2)
        rows.append((True, monitor.confirm(Alert("benchmark", "cpu", value, baseline))["confirmed"]))
    true_positive = sum(actual and predicted for actual, predicted in rows)
    false_positive = sum((not actual) and predicted for actual, predicted in rows)
    false_negative = sum(actual and (not predicted) for actual, predicted in rows)
    true_negative = sum((not actual) and (not predicted) for actual, predicted in rows)
    report = {
        "seed": 20260829,
        "samples": len(rows),
        "detectors": ["3-sigma", "EWMA", "isolation-forest"],
        "confusion_matrix": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "precision": round(true_positive / max(true_positive + false_positive, 1), 4),
        "recall": round(true_positive / max(true_positive + false_negative, 1), 4),
    }
    output = Path(__file__).resolve().parents[1] / "07_Logs" / "local_detection_benchmark.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
