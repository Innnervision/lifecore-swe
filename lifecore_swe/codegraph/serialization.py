"""Graph serialization and deserialization utilities."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .schema import Node, Edge


class GraphSerializer:
    """Serializes repository graph to JSONL and metadata files."""

    PARSER_VERSION = "1.0.0"

    @classmethod
    def save_graph(
        cls,
        nodes: Dict[str, Node],
        edges: Dict[str, Edge],
        output_dir: str,
        repo_path: str,
        repo_id: str,
    ) -> Dict[str, str]:
        """Save graph entities and relationships into output directory."""
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        nodes_file = out_path / "nodes.jsonl"
        edges_file = out_path / "edges.jsonl"
        meta_file = out_path / "metadata.json"

        # 1. Write nodes.jsonl
        with open(nodes_file, "w", encoding="utf-8") as f:
            for node in sorted(nodes.values(), key=lambda n: n.node_id):
                f.write(json.dumps(node.to_dict()) + "\n")

        # 2. Write edges.jsonl
        with open(edges_file, "w", encoding="utf-8") as f:
            for edge in sorted(edges.values(), key=lambda e: e.edge_id):
                f.write(json.dumps(edge.to_dict()) + "\n")

        # 3. Get git commit/version if available
        commit_hash = "NOT_AVAILABLE"
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                commit_hash = res.stdout.strip()
        except Exception:
            pass

        # 4. Write metadata.json
        metadata = {
            "repository": repo_id,
            "commit_version": commit_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parser_version": cls.PARSER_VERSION,
            "language": "python",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": {
                nt: sum(1 for n in nodes.values() if n.node_type == nt)
                for nt in set(n.node_type for n in nodes.values())
            },
            "edge_types": {
                et: sum(1 for e in edges.values() if e.edge_type == et)
                for et in set(e.edge_type for e in edges.values())
            },
        }

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {
            "nodes_file": str(nodes_file),
            "edges_file": str(edges_file),
            "metadata_file": str(meta_file),
        }

    @classmethod
    def load_graph(cls, input_dir: str) -> Tuple[Dict[str, Node], Dict[str, Edge], Dict]:
        """Load graph from serialized JSONL and metadata files."""
        in_path = Path(input_dir).resolve()
        nodes: Dict[str, Node] = {}
        edges: Dict[str, Edge] = {}
        metadata: Dict = {}

        nodes_file = in_path / "nodes.jsonl"
        edges_file = in_path / "edges.jsonl"
        meta_file = in_path / "metadata.json"

        if nodes_file.exists():
            with open(nodes_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        nodes[d["node_id"]] = Node.from_dict(d)

        if edges_file.exists():
            with open(edges_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        edges[d["edge_id"]] = Edge.from_dict(d)

        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

        return nodes, edges, metadata
