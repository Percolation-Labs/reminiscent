#!/usr/bin/env python3
"""Export annotated feedback from Phoenix to CSV.

Usage:
    python scripts/export_phoenix_feedback.py --ndata 100
    python scripts/export_phoenix_feedback.py --output feedback.csv
    python scripts/export_phoenix_feedback.py --ndata 50 --output my_feedback.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import httpx


def get_phoenix_config():
    """Get Phoenix API key and URL from environment or k8s secrets."""
    import os

    # Try environment first
    api_key = os.environ.get("PHOENIX_API_KEY")
    base_url = os.environ.get("PHOENIX_URL", "http://localhost:6006")

    if not api_key:
        # Try to get from settings
        try:
            from rem.settings import settings
            api_key = settings.phoenix.api_key
            if settings.phoenix.base_url:
                base_url = settings.phoenix.base_url
        except Exception:
            pass

    if not api_key:
        print("Error: PHOENIX_API_KEY not set. Either:")
        print("  1. Set PHOENIX_API_KEY environment variable")
        print("  2. Configure in rem settings")
        print("  3. Port-forward Phoenix and set the API key:")
        print("     kubectl port-forward -n rem svc/phoenix 6006:6006")
        sys.exit(1)

    return api_key, base_url


def fetch_annotated_spans(client: httpx.Client, headers: dict, base_url: str, ndata: int | None = None) -> list[dict]:
    """Fetch spans that have annotations via GraphQL."""

    query = """
    query GetSpansWithAnnotationSummaries($first: Int!, $after: String) {
      node(id: "UHJvamVjdDox") {
        ... on Project {
          spans(first: $first, after: $after) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              node {
                id
                name
                spanId
                startTime
                endTime
                latencyMs
                input { value }
                output { value }
                spanAnnotationSummaries { count name }
              }
            }
          }
        }
      }
    }
    """

    annotated_spans = []
    cursor = None
    page = 0

    while True:
        variables = {"first": 100, "after": cursor}
        resp = client.post(
            f"{base_url}/graphql",
            headers=headers,
            json={"query": query, "variables": variables}
        )

        data = resp.json()
        if "errors" in data:
            print(f"GraphQL errors: {data['errors']}")
            break

        spans_data = data.get("data", {}).get("node", {}).get("spans", {})
        edges = spans_data.get("edges", [])
        page_info = spans_data.get("pageInfo", {})

        page += 1

        for edge in edges:
            node = edge.get("node", {})
            summaries = node.get("spanAnnotationSummaries", [])
            if summaries and any(s.get("count", 0) > 0 for s in summaries):
                annotated_spans.append({
                    "span_id": node.get("spanId"),
                    "name": node.get("name"),
                    "start_time": node.get("startTime"),
                    "end_time": node.get("endTime"),
                    "latency_ms": node.get("latencyMs"),
                    "input": node.get("input", {}).get("value", ""),
                    "output": node.get("output", {}).get("value", ""),
                })

                # Check if we've reached the limit
                if ndata and len(annotated_spans) >= ndata:
                    print(f"Reached limit of {ndata} annotated spans")
                    return annotated_spans

        print(f"Page {page}: processed {len(edges)} spans, found {len(annotated_spans)} with annotations")

        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return annotated_spans


def fetch_annotations(client: httpx.Client, headers: dict, base_url: str, span_ids: list[str]) -> list[dict]:
    """Fetch annotation details for given span IDs."""

    annotations = []

    for i, span_id in enumerate(span_ids):
        resp = client.get(
            f"{base_url}/v1/projects/default/span_annotations",
            headers=headers,
            params={"span_ids": span_id}
        )

        if resp.status_code == 200:
            ann_data = resp.json().get("data", [])
            for ann in ann_data:
                ann["_span_id"] = span_id
            annotations.extend(ann_data)

        if (i + 1) % 20 == 0:
            print(f"  Fetched annotations for {i + 1}/{len(span_ids)} spans")

    return annotations


def main():
    parser = argparse.ArgumentParser(description="Export annotated feedback from Phoenix to CSV")
    parser.add_argument("--ndata", type=int, help="Maximum number of annotated spans to fetch")
    parser.add_argument("--output", "-o", type=str, default="phoenix_annotated_feedback.csv",
                        help="Output CSV file path (default: phoenix_annotated_feedback.csv)")
    parser.add_argument("--base-url", type=str, help="Phoenix base URL (default: http://localhost:6006)")
    parser.add_argument("--api-key", type=str, help="Phoenix API key (or set PHOENIX_API_KEY env var)")

    args = parser.parse_args()

    # Get config
    if args.api_key:
        api_key = args.api_key
        base_url = args.base_url or "http://localhost:6006"
    else:
        api_key, base_url = get_phoenix_config()

    if args.base_url:
        base_url = args.base_url

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = httpx.Client(timeout=120.0)

    try:
        # Step 1: Find spans with annotations
        print(f"Connecting to Phoenix at {base_url}")
        print(f"Step 1: Finding spans with annotations{f' (limit: {args.ndata})' if args.ndata else ''}...")

        annotated_spans = fetch_annotated_spans(client, headers, base_url, args.ndata)
        print(f"\nFound {len(annotated_spans)} spans with annotations")

        if not annotated_spans:
            print("No annotated spans found.")
            return

        # Step 2: Fetch annotation details
        print("\nStep 2: Fetching annotation details...")
        span_id_to_info = {s["span_id"]: s for s in annotated_spans}
        annotations = fetch_annotations(
            client,
            {"Authorization": f"Bearer {api_key}"},
            base_url,
            list(span_id_to_info.keys())
        )

        print(f"\nTotal annotation records: {len(annotations)}")

        # Step 3: Build records and write CSV
        records = []
        for ann in annotations:
            span_id = ann["_span_id"]
            span_info = span_id_to_info.get(span_id, {})

            record = {
                "span_id": span_id,
                "span_name": span_info.get("name", ""),
                "span_start_time": span_info.get("start_time", ""),
                "span_end_time": span_info.get("end_time", ""),
                "span_latency_ms": span_info.get("latency_ms", ""),
                "span_input": (span_info.get("input") or "")[:500],
                "span_output": (span_info.get("output") or "")[:500],
                "annotation_id": ann.get("id"),
                "annotation_name": ann.get("name"),
                "annotator_kind": ann.get("annotator_kind"),
                "label": ann.get("result", {}).get("label"),
                "score": ann.get("result", {}).get("score"),
                "explanation": ann.get("result", {}).get("explanation"),
                "annotation_created_at": ann.get("created_at"),
                "annotation_metadata": json.dumps(ann.get("metadata", {})),
            }
            records.append(record)

        # Write CSV
        output_path = Path(args.output)
        if records:
            fieldnames = list(records[0].keys())
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
            print(f"\n✓ Saved {len(records)} records to {output_path}")

            # Show label distribution
            from collections import Counter
            labels = Counter(r["label"] for r in records)
            print("\nLabel distribution:")
            for label, count in labels.most_common():
                print(f"  {label or '(no label)'}: {count}")
        else:
            print("\nNo records to save.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
