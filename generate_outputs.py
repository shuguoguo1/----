"""生成基础计算器要求的CSV与DEM高程剖面图。"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from src.config import DEFAULT_OUTPUT_DIR, DEFAULT_PROBLEM_ROOT
from src.flight_calculator import SegmentCalculator


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"没有可写入的数据：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def configure_chinese_font() -> str:
    import matplotlib
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    ]
    selected = next((font for font in candidates if font in available), "DejaVu Sans")
    matplotlib.rcParams["font.sans-serif"] = [selected, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return selected


def save_elevation_profile(
    calculator: SegmentCalculator,
    output_dir: Path,
    start_node: str = "O01",
    end_node: str = "S015",
) -> dict:
    import matplotlib.pyplot as plt

    selected_font = configure_chinese_font()
    profile = calculator.terrain_profile(start_node, end_node)
    cruise_altitude_m = profile.max_terrain_elevation_m + 50.0
    distance_km = profile.distance_m / 1000.0

    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    ax.plot(
        distance_km,
        profile.elevation_m,
        color="#0072B2",
        linewidth=1.5,
        label="沿线地面高程",
    )
    ax.axhline(
        cruise_altitude_m,
        color="#D55E00",
        linestyle="--",
        linewidth=1.4,
        label="计划巡航海拔（最高地形 + 50 m）",
    )
    max_index = int(np.nanargmax(profile.elevation_m))
    ax.scatter(
        [distance_km[max_index]],
        [profile.elevation_m[max_index]],
        color="#000000",
        marker="o",
        s=28,
        zorder=3,
        label="最高地形点",
    )
    ax.set_xlabel("沿路线累计距离（km）")
    ax.set_ylabel("海拔（m）")
    ax.set_title(f"{start_node} → {end_node} DEM高程剖面")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6, linestyle=":")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best")

    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "demo_elevation_profile.png"
    svg_path = output_dir / "demo_elevation_profile.svg"
    grayscale_path = output_dir / "demo_elevation_profile_grayscale.png"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")

    for line in ax.lines:
        line.set_color("#222222")
    for collection in ax.collections:
        collection.set_facecolor("#111111")
        collection.set_edgecolor("#111111")
    fig.savefig(grayscale_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {
        "route": f"{start_node}->{end_node}",
        "font": selected_font,
        "png": str(png_path.resolve()),
        "svg": str(svg_path.resolve()),
        "grayscale_png": str(grayscale_path.resolve()),
        "sample_count": len(profile.distance_m),
        "horizontal_distance_m": profile.horizontal_distance_m,
        "max_terrain_elevation_m": profile.max_terrain_elevation_m,
        "cruise_altitude_m": cruise_altitude_m,
    }


def build_outputs(problem_root: Path, output_dir: Path) -> dict:
    calculator = SegmentCalculator(problem_root=problem_root)

    node_pair_rows = calculator.all_node_pair_geometry()
    write_csv(output_dir / "node_pair_geometry.csv", node_pair_rows)

    demo = calculator.calculate_segment("O01", "S001", "A", 20.0)
    write_csv(output_dir / "segment_demo.csv", [demo])

    segment_rows: list[dict] = []
    demo_routes = [
        ("O01", "S001"),
        ("O01", "S003"),
        ("O01", "S010"),
        ("O01", "S015"),
    ]
    for model_id, model in calculator.data.models.items():
        for payload_fraction in (0.0, 0.5, 0.95):
            payload_kg = model.max_payload_kg * payload_fraction
            for start_node, end_node in demo_routes:
                segment_rows.append(
                    calculator.calculate_segment(
                        start_node, end_node, model_id, payload_kg
                    )
                )
    write_csv(output_dir / "segment_cost_demo.csv", segment_rows)
    figure_info = save_elevation_profile(calculator, output_dir)

    return {
        "source_manifest": calculator.source_manifest,
        "dem_metadata": calculator.dem.metadata,
        "node_count": len(calculator.data.nodes),
        "model_count": len(calculator.data.models),
        "node_pair_count": len(node_pair_rows),
        "segment_demo": demo,
        "segment_cost_demo_count": len(segment_rows),
        "figure": figure_info,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成D题基础航段计算器输出")
    parser.add_argument("--problem-root", type=Path, default=DEFAULT_PROBLEM_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    summary = build_outputs(args.problem_root, args.output_dir)

    print("基础航段计算器输出已生成")
    print(f"节点数：{summary['node_count']}")
    print(f"机型数：{summary['model_count']}")
    print(f"有向节点对数：{summary['node_pair_count']}")
    print(f"典型航段成本记录数：{summary['segment_cost_demo_count']}")
    print(f"高程剖面：{summary['figure']['png']}")
    print("O01 -> S001，A型，20 kg 示例：")
    for key, value in summary["segment_demo"].items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
