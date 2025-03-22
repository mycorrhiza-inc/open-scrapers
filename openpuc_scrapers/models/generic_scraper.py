from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any, Dict, Generic, TypeVar, List, Type
from datetime import date, datetime, timezone
from pydantic import BaseModel

from openpuc_scrapers.models.filing import GenericFiling as GenericFilingData
from openpuc_scrapers.models.case import GenericCase as GenericCaseData
from openpuc_scrapers.models.misc import (
    RequestData,
    post_list_to_endpoint_split,
)

StateCaseData = TypeVar("StateCaseData", bound=BaseModel)
StateFilingData = TypeVar("StateFilingData", bound=BaseModel)


"""
To create a New State Specific Scraper.

1. Go ahead and define two types related to the data you want to scrape. StateCaseData, StateFilingData.

2. Create a new class with name <StateName>Scraper

To create a New State Specific Scraper, implement three main functionalities:

1. Universal Case List: Get a list of all cases in the system
2. Filing Data: Get detailed filing data for a specific case
3. Updated Cases: Get cases that have been updated since a given date

Each functionality requires two steps due to saving JSON-serializable intermediates to disk:

1. Universal Case List Steps:
   ```python
   def universal_caselist_intermediate(self) -> Dict[str, Any]:
   def universal_caselist_from_intermediate(self, intermediate: Dict[str, Any]) -> List[StateCaseData]:
   ```

2. Filing Data Steps:
   ```python
   def filing_data_intermediate(self, data: StateCaseData) -> Dict[str, Any]:
   def filing_data_from_intermediate(self, intermediate: Dict[str, Any]) -> List[StateFilingData]:
   ```

3. Updated Cases Steps:
   ```python
   def updated_cases_since_date_intermediate(self, after_date: date) -> Dict[str, Any]:
   
   def updated_cases_since_date_from_intermediate(self, intermediate: Dict[str, Any], after_date: date) -> List[StateCaseData]:
   ```

Additionally, implement conversion methods to transform state-specific types into generic types:

```python
def into_generic_case_data(self, state_data: StateCaseData) -> GenericCaseData:
def into_generic_filing_data(self, state_data: StateFilingData) -> GenericFilingData:

The intermediate objects must be JSON-serializable (Dict[str,Any]). Each intermediate output must be parsable by its corresponding from_intermediate method:

- universal_caselist_intermediate() → universal_caselist_from_intermediate()
- filing_data_intermediate() → filing_data_from_intermediate()
- updated_cases_since_date_intermediate() → updated_cases_since_date_from_intermediate()
"""


class GenericScraper(ABC, Generic[StateCaseData, StateFilingData]):
    # Universal case list methods
    @abstractmethod
    def universal_caselist_intermediate(self) -> Dict[str, Any]:
        """Return intermediate representation of case list"""
        pass

    @abstractmethod
    def universal_caselist_from_intermediate(
        self, intermediate: Dict[str, Any]
    ) -> List[StateCaseData]:
        """Convert intermediate to state-specific case data objects"""
        pass

    # GenericFiling data methods
    @abstractmethod
    def filing_data_intermediate(self, data: StateCaseData) -> Dict[str, Any]:
        """Serialize case data to intermediate format"""
        pass

    @abstractmethod
    def filing_data_from_intermediate(
        self, intermediate: Dict[str, Any]
    ) -> List[StateFilingData]:
        """Convert intermediate to state-specific filing data objects"""
        pass

    # Updated cases methods
    @abstractmethod
    def updated_cases_since_date_intermediate(self, after_date: date) -> Dict[str, Any]:
        """Get intermediate for cases updated after given date"""
        pass

    @abstractmethod
    def updated_cases_since_date_from_intermediate(
        self, intermediate: Dict[str, Any], after_date: date
    ) -> List[StateCaseData]:
        """Convert intermediate to updated case data objects"""
        pass

    # Conversion methods to generic types
    @abstractmethod
    def into_generic_case_data(self, state_data: StateCaseData) -> GenericCaseData:
        """Convert state-specific case data to generic format"""
        pass

    @abstractmethod
    def into_generic_filing_data(
        self, state_data: StateFilingData
    ) -> GenericFilingData:
        """Convert state-specific filing data to generic format"""
        pass


# Helper functions
def save_to_disk(path: str, content: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


# isnt working due to the higher order types sadly
# def save_json(path: str, data: BaseModel | List[BaseModel]) -> None:
def save_json(path: str, data: Any) -> None:
    if isinstance(data, dict):
        json_data = data
    if isinstance(data, BaseModel):
        json_data = data.model_dump()
    if isinstance(data, list):
        json_data = [item.model_dump() for item in data]
    else:
        raise Exception("Data is not a list, dict, or BaseModel")
    json_str = json.dumps(json_data, indent=2)
    save_to_disk(path, json_str)


# Processing functions
def process_cases(
    scraper: GenericScraper[StateCaseData, StateFilingData],
    cases: List[StateCaseData],
    base_path: str,
) -> List[GenericCaseData]:
    all_generic_cases = []

    for case in cases:
        generic_case = scraper.into_generic_case_data(case)
        case_num = generic_case.case_number

        # Save state-specific case data
        case_path = f"{base_path}/cases/case_{case_num}.json"
        save_json(case_path, case)

        # Process filings
        filings_intermediate = scraper.filing_data_intermediate(case)
        filings_path = f"{base_path}/filings/case_{case_num}.json"
        save_json(filings_path, filings_intermediate)

        filings = scraper.filing_data_from_intermediate(filings_intermediate)
        filings_json_path = f"{base_path}/filings/case_{case_num}.json"
        save_json(filings_json_path, filings)

        # Convert to generic case
        generic_case = scraper.into_generic_filing_data

        case_specific_generic_cases = []
        for filing in filings:
            generic_filing = scraper.into_generic_filing_data(filing)
            case_specific_generic_cases.append(generic_filing)
        all_generic_cases.extend(case_specific_generic_cases)

    return all_generic_cases


def get_all_cases(
    scraper: GenericScraper[StateCaseData, StateFilingData]
) -> List[GenericCaseData]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_path = f"data/{timestamp}"

    # Get and save case list
    caselist_intermediate = scraper.universal_caselist_intermediate()
    caselist_path = f"{base_path}/caselist.json"
    save_json(caselist_path, caselist_intermediate)

    # Process cases
    state_cases = scraper.universal_caselist_from_intermediate(caselist_intermediate)
    return process_cases(scraper, state_cases, base_path)


def get_new_cases_since_date(
    scraper: GenericScraper[StateCaseData, StateFilingData], after_date: date
) -> List[GenericCaseData]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_path = f"data/{timestamp}"

    # Get and save updated cases
    updated_intermediate = scraper.updated_cases_since_date_intermediate(after_date)
    updated_path = f"{base_path}/updated_cases.json"
    save_json(updated_path, updated_intermediate)

    # Process updated cases
    state_cases = scraper.updated_cases_since_date_from_intermediate(
        updated_intermediate, after_date
    )
    return process_cases(scraper, state_cases, base_path)


async def scrape_and_send_cases_to_endpoint(
    scraper: GenericScraper,
    post_endpoint: str,
    max_request_size: int = 1000,
    max_simul_requests: int = 10,
) -> List[dict]:
    cases = get_all_cases(scraper)

    return await post_list_to_endpoint_split(
        objects=cases,
        post_endpoint=post_endpoint,
        max_simul_requests=max_simul_requests,
        max_request_size=max_request_size,
    )
