"""사진 GPS 이동속도로 비행 중 촬영 후보를 찾는다.

이 스크립트는 사진 원본을 열지 않고 newphotos_with.json만 읽는다.
결과는 검토용 flight_candidates.json에 저장하며 자동으로 지도를 수정하지 않는다.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "newphotos_with.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "flight_candidates.json"

# 같은 장소에서 연속 촬영한 사진을 한 묶음으로 정리하기 위한 기준
STATIONARY_DISTANCE_KM = 2.0
STATIONARY_MAX_MINUTES = 30.0

# 비행 가능성이 있는 이동 구간 판정 기준
MIN_FLIGHT_SPEED_KMH = 250.0
MIN_FLIGHT_DISTANCE_KM = 30.0
MAX_EDGE_GAP_HOURS = 12.0


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def haversine_km(lat1, lng1, lat2, lng2):
    radius_km = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def load_records(path, year):
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = []
    invalid = 0

    for item in raw:
        captured_at = parse_time(item.get("time"))
        lat = item.get("lat")
        lng = item.get("lng")
        if (
            captured_at is None
            or captured_at.year != year
            or not isinstance(lat, (int, float))
            or not isinstance(lng, (int, float))
        ):
            if item.get("time") and str(item.get("time")).startswith(str(year)):
                invalid += 1
            continue

        records.append(
            {
                "file": item.get("file", ""),
                "time": captured_at,
                "lat": float(lat),
                "lng": float(lng),
            }
        )

    records.sort(key=lambda record: (record["time"], record["file"]))
    return records, invalid


def cluster_stationary_records(records):
    """가까운 장소에서 짧은 시간 안에 찍은 연속 사진을 한 묶음으로 만든다."""
    clusters = []

    for record in records:
        if not clusters:
            clusters.append(
                {
                    "start": record["time"],
                    "end": record["time"],
                    "lat": record["lat"],
                    "lng": record["lng"],
                    "records": [record],
                }
            )
            continue

        current = clusters[-1]
        gap_minutes = (record["time"] - current["end"]).total_seconds() / 60
        distance = haversine_km(
            current["lat"], current["lng"], record["lat"], record["lng"]
        )

        if (
            0 <= gap_minutes <= STATIONARY_MAX_MINUTES
            and distance <= STATIONARY_DISTANCE_KM
        ):
            current["records"].append(record)
            current["end"] = record["time"]
            count = len(current["records"])
            current["lat"] = (
                current["lat"] * (count - 1) + record["lat"]
            ) / count
            current["lng"] = (
                current["lng"] * (count - 1) + record["lng"]
            ) / count
        else:
            clusters.append(
                {
                    "start": record["time"],
                    "end": record["time"],
                    "lat": record["lat"],
                    "lng": record["lng"],
                    "records": [record],
                }
            )

    return clusters


def suspicious_edges(clusters):
    edges = []

    for index in range(len(clusters) - 1):
        left = clusters[index]
        right = clusters[index + 1]
        hours = (right["start"] - left["end"]).total_seconds() / 3600
        if hours <= 0 or hours > MAX_EDGE_GAP_HOURS:
            continue

        distance = haversine_km(
            left["lat"], left["lng"], right["lat"], right["lng"]
        )
        speed = distance / hours
        if distance >= MIN_FLIGHT_DISTANCE_KM and speed >= MIN_FLIGHT_SPEED_KMH:
            edges.append(
                {
                    "index": index,
                    "distance_km": distance,
                    "hours": hours,
                    "speed_kmh": speed,
                }
            )

    return edges


def consecutive_edge_runs(edges):
    if not edges:
        return []

    runs = [[edges[0]]]
    for edge in edges[1:]:
        if edge["index"] == runs[-1][-1]["index"] + 1:
            runs[-1].append(edge)
        else:
            runs.append([edge])
    return runs


def cluster_context(cluster):
    return {
        "start": cluster["start"].strftime("%Y-%m-%d %H:%M:%S"),
        "end": cluster["end"].strftime("%Y-%m-%d %H:%M:%S"),
        "lat": round(cluster["lat"], 2),
        "lng": round(cluster["lng"], 2),
        "photo_count": len(cluster["records"]),
    }


def edge_context(edge, clusters):
    left = clusters[edge["index"]]
    right = clusters[edge["index"] + 1]
    return {
        "from": cluster_context(left),
        "to": cluster_context(right),
        "from_file": left["records"][-1]["file"],
        "to_file": right["records"][0]["file"],
        "distance_km": round(edge["distance_km"], 1),
        "elapsed_hours": round(edge["hours"], 2),
        "speed_kmh": round(edge["speed_kmh"], 1),
    }


def build_candidate_groups(clusters, edges):
    groups = []

    # 한 번의 장거리 점프만 있는 경우는 출발지/도착지 지상 사진일 수 있으므로
    # 자동 후보에서 제외한다. 연속된 고속 이동이 두 구간 이상일 때만 중간
    # 지점의 사진을 비행 중 촬영 후보로 제시한다.
    for run_number, run in enumerate(consecutive_edge_runs(edges), start=1):
        if len(run) < 2:
            continue

        first_edge_index = run[0]["index"]
        last_edge_index = run[-1]["index"]
        candidate_clusters = clusters[first_edge_index + 1 : last_edge_index + 1]
        candidate_records = [
            record
            for cluster in candidate_clusters
            for record in cluster["records"]
        ]
        if not candidate_records:
            continue

        max_speed = max(edge["speed_kmh"] for edge in run)
        confidence = "high" if len(run) >= 3 or len(candidate_records) >= 3 else "medium"
        start_time = candidate_records[0]["time"]
        end_time = candidate_records[-1]["time"]

        groups.append(
            {
                "id": f"flight-{start_time:%Y%m%d-%H%M}-{run_number}",
                "confidence": confidence,
                "start": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "candidate_photo_count": len(candidate_records),
                "candidate_files": [record["file"] for record in candidate_records],
                "candidate_points": [
                    {
                        "file": record["file"],
                        "time": record["time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "lat": round(record["lat"], 2),
                        "lng": round(record["lng"], 2),
                    }
                    for record in candidate_records
                ],
                "context_before": cluster_context(clusters[first_edge_index]),
                "context_after": cluster_context(clusters[last_edge_index + 1]),
                "edge_count": len(run),
                "max_speed_kmh": round(max_speed, 1),
                "total_edge_distance_km": round(
                    sum(edge["distance_km"] for edge in run), 1
                ),
                "approved": False,
            }
        )

    return groups


def load_existing_approvals(path):
    """재탐지해도 사용자가 승인한 후보 설정을 가능한 한 유지한다."""
    if not path.exists():
        return {}, {}
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(previous, dict):
        return {}, {}

    by_id = {}
    by_range = {}
    for group in previous.get("candidate_groups", []):
        if not isinstance(group, dict) or group.get("approved") is not True:
            continue
        preserved = {"approved": True}
        for key in ("name", "buffer_before_hours", "buffer_after_hours"):
            if key in group:
                preserved[key] = group[key]
        if group.get("id"):
            by_id[group["id"]] = preserved
        if group.get("start") and group.get("end"):
            by_range[(group["start"], group["end"])] = preserved
    return by_id, by_range


def restore_approvals(groups, output_path):
    by_id, by_range = load_existing_approvals(output_path)
    restored = 0
    for group in groups:
        preserved = by_id.get(group["id"]) or by_range.get(
            (group["start"], group["end"])
        )
        if preserved:
            group.update(preserved)
            restored += 1
    return restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    records, invalid = load_records(args.input, args.year)
    clusters = cluster_stationary_records(records)
    edges = suspicious_edges(clusters)
    groups = build_candidate_groups(clusters, edges)
    restored_approvals = restore_approvals(groups, args.output)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": args.year,
        "input_record_count": len(records),
        "invalid_time_count": invalid,
        "rules": {
            "stationary_distance_km": STATIONARY_DISTANCE_KM,
            "stationary_max_minutes": STATIONARY_MAX_MINUTES,
            "min_flight_speed_kmh": MIN_FLIGHT_SPEED_KMH,
            "min_flight_distance_km": MIN_FLIGHT_DISTANCE_KM,
            "max_edge_gap_hours": MAX_EDGE_GAP_HOURS,
            "minimum_consecutive_fast_edges": 2,
        },
        "candidate_group_count": len(groups),
        "restored_approval_count": restored_approvals,
        "candidate_photo_count": sum(
            group["candidate_photo_count"] for group in groups
        ),
        "fast_edges": [edge_context(edge, clusters) for edge in edges],
        "candidate_groups": groups,
        "note": (
            "자동 후보이며 지도에서 아직 제외되지 않았습니다. "
            "approved 값은 검토 후에만 true로 변경하세요."
        ),
    }

    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"분석 연도: {args.year}")
    print(f"GPS 사진: {len(records)}개")
    print(f"정지 구간 묶음: {len(clusters)}개")
    print(f"고속 이동 구간: {len(edges)}개")
    print(f"비행 후보 그룹: {len(groups)}개")
    print(f"비행 후보 사진: {result['candidate_photo_count']}개")
    print(f"유지된 기존 승인: {restored_approvals}개")
    for edge in result["fast_edges"]:
        print(
            "- 고속 이동 검토: "
            f"{edge['from']['end']} "
            f"({edge['from']['lat']}, {edge['from']['lng']}) -> "
            f"{edge['to']['start']} "
            f"({edge['to']['lat']}, {edge['to']['lng']}), "
            f"{edge['distance_km']}km / {edge['elapsed_hours']}시간 / "
            f"{edge['speed_kmh']}km/h"
        )
    for group in groups:
        print(
            f"- {group['id']}: {group['start']} ~ {group['end']}, "
            f"사진 {group['candidate_photo_count']}개, "
            f"최고 추정속도 {group['max_speed_kmh']}km/h, "
            f"신뢰도 {group['confidence']}"
        )
    print(f"검토 파일: {args.output}")


if __name__ == "__main__":
    main()
