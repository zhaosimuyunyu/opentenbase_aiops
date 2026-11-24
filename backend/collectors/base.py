"""Base collector interface"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class BaseCollector(ABC):
    """Base class for data collectors"""

    def __init__(self, db_connector):
        self.db = db_connector
        self.errors = []

    def _record_error(self, check: str, error: Exception):
        self.errors.append({'check': check, 'error': str(error)})

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """Collect data and return structured result"""
        pass

    def _create_result(
        self,
        status: str,
        data: Any = None,
        error: str = None
    ) -> Dict[str, Any]:
        """Create standardized result structure"""
        result = {
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'collector': self.__class__.__name__
        }
        if status == 'success' and self.errors:
            result['status'] = 'partial'
        if self.errors:
            result['errors'] = list(self.errors)

        if data is not None:
            result['data'] = data

        if error:
            result['error'] = error

        return result
