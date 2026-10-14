"""Resource Graph Builder: Constructs provenance-aware relational graphs from external resource records.

Infers canonical structural relationships:
- SOURCED_FROM (Resource -> Source)
- DOCUMENTS (Documentation / API -> Package / Repository)
- VERSION_OF (PackageVersion -> Package)
- EXAMPLE_FOR (CodeExample -> Package / API)
- DEPENDS_ON (Package / Resource -> Dependency Package)
- REFERENCES (Resource -> Parent / Referenced Resource)
- CONTRADICTS (Resource -> Contradicted Resource)
- SUPERSEDES (New Version / Resource -> Obsolete Resource)
- VALIDATED_BY (Resource -> Validator Entity)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Union

from ..models import FreshnessStatus, ResourceRecord, ResourceType, ResourceVerificationStatus
from ..provenance import ProvenanceRecord
from ..registry import ResourceRegistry
from ..store import ResourceStore
from .index import ResourceGraph
from .schema import ResourceEdge, ResourceEdgeType, ResourceNode, ResourceNodeType


def _clean_dep_name(dep_string: str) -> str:
    """Extract bare package name from dependency specification (e.g. 'urllib3<3,>=1.21.1')."""
    match = re.match(r"^([a-zA-Z0-9_\-\.]+)", dep_string.strip())
    if match:
        return match.group(1).lower()
    return dep_string.strip().lower()


class ResourceGraphBuilder:
    """Builds a connected ResourceGraph from records, stores, or registries."""

    def __init__(self) -> None:
        pass

    def build_from_records(
        self,
        records: List[ResourceRecord],
        provenances: Optional[List[ProvenanceRecord]] = None,
    ) -> ResourceGraph:
        """Construct a complete ResourceGraph from resource and provenance records."""
        graph = ResourceGraph()
        prov_map: Dict[str, ProvenanceRecord] = {}
        if provenances:
            for p in provenances:
                prov_map[p.provenance_id] = p

        # 1. Add discrete resource nodes
        for rec in records:
            node = ResourceNode.from_resource_record(rec)
            graph.add_node(node)

        # 2. Add structural entities (Source, Package, Repository) and edges
        for rec in records:
            self._link_source_entity(graph, rec)
            self._link_package_entity(graph, rec)
            self._link_repository_entity(graph, rec)
            self._link_hierarchy_and_dependencies(graph, rec)
            self._link_lifecycle_relationships(graph, rec)

        return graph

    def build_from_registry(self, registry: ResourceRegistry) -> ResourceGraph:
        """Construct graph from all records in a ResourceRegistry."""
        records = registry.store.list_resources(limit=10000)
        provenances = registry.store.list_provenances(limit=10000)
        return self.build_from_records(records, provenances)

    def build_from_store(self, store: ResourceStore) -> ResourceGraph:
        """Construct graph from all records in a ResourceStore."""
        records = store.list_resources(limit=10000)
        provenances = store.list_provenances(limit=10000)
        return self.build_from_records(records, provenances)

    def _link_source_entity(self, graph: ResourceGraph, rec: ResourceRecord) -> None:
        """Ensure Source entity exists and link with SOURCED_FROM edge."""
        if not rec.source:
            return

        source_id = f"source:{rec.source.strip().lower()}"
        if not graph.get_node(source_id):
            source_node = ResourceNode(
                node_id=source_id,
                node_type=ResourceNodeType.SOURCE,
                title=f"Source: {rec.source}",
                source=rec.source,
                description=f"External source provider: {rec.source}",
                confidence=1.0,
                verification_status=ResourceVerificationStatus.VERIFIED,
                freshness=FreshnessStatus.FRESH,
                provenance_id=rec.provenance_id,
            )
            graph.add_node(source_node)

        edge_id = f"{rec.resource_id}--SOURCED_FROM-->{source_id}"
        if not graph.get_edge(edge_id):
            edge = ResourceEdge(
                edge_id=edge_id,
                source_id=rec.resource_id,
                target_id=source_id,
                edge_type=ResourceEdgeType.SOURCED_FROM,
                provenance_id=rec.provenance_id,
                confidence=rec.confidence,
                evidence=f"Resource {rec.resource_id} originated from source {rec.source}.",
            )
            graph.add_edge(edge)

    def _link_package_entity(self, graph: ResourceGraph, rec: ResourceRecord) -> None:
        """Ensure Package entity exists and link with DOCUMENTS, VERSION_OF, or EXAMPLE_FOR."""
        if not rec.package_name:
            return

        pkg_name = rec.package_name.strip().lower()
        pkg_id = f"package:{pkg_name}"
        if not graph.get_node(pkg_id):
            pkg_node = ResourceNode(
                node_id=pkg_id,
                node_type=ResourceNodeType.PACKAGE,
                title=f"Package: {pkg_name}",
                source=rec.source,
                package_name=pkg_name,
                description=f"Software package: {pkg_name}",
                confidence=1.0,
                verification_status=rec.verification_status,
                freshness=rec.freshness,
                provenance_id=rec.provenance_id,
            )
            graph.add_node(pkg_node)

        # Determine relational edge type
        if rec.resource_type == ResourceType.PACKAGE_VERSION:
            edge_type = ResourceEdgeType.VERSION_OF
        elif rec.resource_type in (ResourceType.DOCUMENTATION, ResourceType.API_REFERENCE):
            edge_type = ResourceEdgeType.DOCUMENTS
        elif rec.resource_type == ResourceType.CODE_EXAMPLE:
            edge_type = ResourceEdgeType.EXAMPLE_FOR
        else:
            edge_type = ResourceEdgeType.RELATED_TO

        edge_id = f"{rec.resource_id}--{edge_type.value}-->{pkg_id}"
        if not graph.get_edge(edge_id):
            edge = ResourceEdge(
                edge_id=edge_id,
                source_id=rec.resource_id,
                target_id=pkg_id,
                edge_type=edge_type,
                provenance_id=rec.provenance_id,
                confidence=rec.confidence,
                evidence=f"Resource {rec.resource_id} has relation {edge_type.value} to package {pkg_name}.",
            )
            graph.add_edge(edge)

    def _link_repository_entity(self, graph: ResourceGraph, rec: ResourceRecord) -> None:
        """Ensure Repository entity exists and link with DOCUMENTS or SOURCED_FROM."""
        if not rec.repository:
            return

        repo_name = rec.repository.strip().lower()
        repo_id = f"repo:{repo_name}"
        if not graph.get_node(repo_id):
            repo_node = ResourceNode(
                node_id=repo_id,
                node_type=ResourceNodeType.REPOSITORY,
                title=f"Repository: {repo_name}",
                source=rec.source,
                repository=repo_name,
                description=f"Code repository: {repo_name}",
                confidence=1.0,
                verification_status=rec.verification_status,
                freshness=rec.freshness,
                provenance_id=rec.provenance_id,
            )
            graph.add_node(repo_node)

        edge_type = ResourceEdgeType.DOCUMENTS if rec.resource_type != ResourceType.REPOSITORY else ResourceEdgeType.RELATED_TO
        edge_id = f"{rec.resource_id}--{edge_type.value}-->{repo_id}"
        if not graph.get_edge(edge_id):
            edge = ResourceEdge(
                edge_id=edge_id,
                source_id=rec.resource_id,
                target_id=repo_id,
                edge_type=edge_type,
                provenance_id=rec.provenance_id,
                confidence=rec.confidence,
                evidence=f"Resource {rec.resource_id} is associated with repository {repo_name}.",
            )
            graph.add_edge(edge)

    def _link_hierarchy_and_dependencies(self, graph: ResourceGraph, rec: ResourceRecord) -> None:
        """Link parent resources (REFERENCES) and dependencies (DEPENDS_ON)."""
        # Parent resource reference
        if rec.parent_resource_id and graph.get_node(rec.parent_resource_id):
            edge_id = f"{rec.resource_id}--REFERENCES-->{rec.parent_resource_id}"
            if not graph.get_edge(edge_id):
                graph.add_edge(
                    ResourceEdge(
                        edge_id=edge_id,
                        source_id=rec.resource_id,
                        target_id=rec.parent_resource_id,
                        edge_type=ResourceEdgeType.REFERENCES,
                        provenance_id=rec.provenance_id,
                        confidence=rec.confidence,
                        evidence=f"Hierarchy link to parent {rec.parent_resource_id}.",
                    )
                )

        # Dependencies
        dependencies = rec.metadata.get("dependencies", [])
        for dep in dependencies:
            if isinstance(dep, str):
                dep_pkg = _clean_dep_name(dep)
                if not dep_pkg:
                    continue
                dep_id = f"package:{dep_pkg}"
                if not graph.get_node(dep_id):
                    dep_node = ResourceNode(
                        node_id=dep_id,
                        node_type=ResourceNodeType.PACKAGE,
                        title=f"Package: {dep_pkg}",
                        source=rec.source,
                        package_name=dep_pkg,
                        description=f"Dependency package: {dep_pkg}",
                        confidence=1.0,
                        verification_status=ResourceVerificationStatus.UNVERIFIED,
                        freshness=FreshnessStatus.UNKNOWN,
                    )
                    graph.add_node(dep_node)

                dep_edge_id = f"{rec.resource_id}--DEPENDS_ON-->{dep_id}"
                if not graph.get_edge(dep_edge_id):
                    graph.add_edge(
                        ResourceEdge(
                            edge_id=dep_edge_id,
                            source_id=rec.resource_id,
                            target_id=dep_id,
                            edge_type=ResourceEdgeType.DEPENDS_ON,
                            provenance_id=rec.provenance_id,
                            confidence=1.0,
                            evidence=f"Declared dependency specification: '{dep}'.",
                        )
                    )

    def _link_lifecycle_relationships(self, graph: ResourceGraph, rec: ResourceRecord) -> None:
        """Link CONTRADICTS, SUPERSEDES, or VALIDATED_BY relationships."""
        # Contradictions
        contradicts_id = rec.metadata.get("contradicts_id")
        if contradicts_id and graph.get_node(contradicts_id):
            edge_id = f"{rec.resource_id}--CONTRADICTS-->{contradicts_id}"
            if not graph.get_edge(edge_id):
                graph.add_edge(
                    ResourceEdge(
                        edge_id=edge_id,
                        source_id=rec.resource_id,
                        target_id=contradicts_id,
                        edge_type=ResourceEdgeType.CONTRADICTS,
                        provenance_id=rec.provenance_id,
                        confidence=1.0,
                        evidence="Identified contradictory metadata between resources.",
                    )
                )

        # Supersedes
        supersedes_id = rec.metadata.get("supersedes_id")
        if supersedes_id and graph.get_node(supersedes_id):
            edge_id = f"{rec.resource_id}--SUPERSEDES-->{supersedes_id}"
            if not graph.get_edge(edge_id):
                graph.add_edge(
                    ResourceEdge(
                        edge_id=edge_id,
                        source_id=rec.resource_id,
                        target_id=supersedes_id,
                        edge_type=ResourceEdgeType.SUPERSEDES,
                        provenance_id=rec.provenance_id,
                        confidence=1.0,
                        evidence="New version/resource supersedes previous entry.",
                    )
                )

        # Validated by
        validated_by = rec.metadata.get("validated_by")
        if validated_by:
            val_id = f"validator:{validated_by}"
            if not graph.get_node(val_id):
                val_node = ResourceNode(
                    node_id=val_id,
                    node_type=ResourceNodeType.RESOURCE,
                    title=f"Validator: {validated_by}",
                    source="internal",
                    description=f"Validation entity or test suite: {validated_by}",
                    confidence=1.0,
                    verification_status=ResourceVerificationStatus.VERIFIED,
                    freshness=FreshnessStatus.FRESH,
                )
                graph.add_node(val_node)

            edge_id = f"{rec.resource_id}--VALIDATED_BY-->{val_id}"
            if not graph.get_edge(edge_id):
                graph.add_edge(
                    ResourceEdge(
                        edge_id=edge_id,
                        source_id=rec.resource_id,
                        target_id=val_id,
                        edge_type=ResourceEdgeType.VALIDATED_BY,
                        provenance_id=rec.provenance_id,
                        confidence=1.0,
                        evidence=f"Validated by {validated_by}.",
                    )
                )
