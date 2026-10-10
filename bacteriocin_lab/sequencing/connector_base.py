"""Base abstract interface for universal sequencing platform connectors."""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any, Callable


class SequencingConnector(abc.ABC):
    """Abstract base class governing all platform-specific sequencing integrations."""

    @property
    @abc.abstractmethod
    def connector_id(self) -> str:
        """Machine identifier (e.g. 'local_folder', 'illumina_basespace', 'oxford_nanopore')."""
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Display name (e.g. 'Illumina BaseSpace Sequence Hub')."""
        ...

    @property
    @abc.abstractmethod
    def vendor(self) -> str:
        """Vendor category ('illumina', 'nanopore', 'pacbio', 'local')."""
        ...

    @property
    @abc.abstractmethod
    def auth_type(self) -> str:
        """Authentication mechanism ('none', 'api_key', 'oauth2', 'token', 'directory_path')."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str: ...

    @abc.abstractmethod
    def capabilities(self) -> list[str]:
        """List of functional capabilities supported by this connector."""
        ...

    @abc.abstractmethod
    def supported_file_types(self) -> list[str]:
        """File extensions recognized by this connector."""
        ...

    @abc.abstractmethod
    def validate_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate credentials or directory accessibility without performing full sync.

        Returns:
            dict with 'valid': bool, 'message': str, 'details': dict.
        """
        ...

    @abc.abstractmethod
    def discover_runs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover runs accessible through this connection.

        Returns list of run metadata dictionaries.
        """
        ...

    @abc.abstractmethod
    def list_datasets(
        self, config: dict[str, Any], external_run_id: str
    ) -> list[dict[str, Any]]:
        """List datasets and files available for a given run."""
        ...

    @abc.abstractmethod
    def import_dataset(
        self,
        config: dict[str, Any],
        dataset: dict[str, Any],
        destination_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Transfer and verify an authorized dataset to local platform storage.

        Args:
            config: connection configuration
            dataset: dataset record to import
            destination_dir: safe local folder where file should be placed
            progress_callback: optional callback receiving (transferred_bytes, total_bytes)

        Returns:
            dict with 'success': bool, 'local_path': str, 'checksum': str, 'error': str | None.
        """
        ...
