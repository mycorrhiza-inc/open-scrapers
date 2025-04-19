from datetime import datetime
from typing import Any, List
from airflow.decorators import dag, task
from openpuc_scrapers.pipelines.generic_pipeline_wrappers import (
    generate_intermediate_object_save_path,
    get_all_caselist_raw,
    process_case,
)
from openpuc_scrapers.scrapers.scraper_lookup import (
    get_scraper_type_from_name_default_dummy,
    get_scraper_type_from_name_unvalidated,
)

# from openpuc_scrapers.models.case import GenericCase
# from openpuc_scrapers.scrapers.base import StateCaseData, StateFilingData
# from functools import partial

default_args = {
    "owner": "airflow",
    "start_date": datetime(2023, 1, 1),
}


@dag(
    default_args=default_args,
    schedule_interval=None,
    params={"scraper_name": "unknown"},
    tags=["scrapers"],
)
def all_cases_dag():
    # TODO: Add the types for this later, rn I am wanting to do things as simply as possible to avoid weird shit

    @task
    def get_all_caselist_raw_airflow(scraper: Any, base_path: str) -> List[Any]:
        return get_all_caselist_raw(scraper=scraper, base_path=base_path)

    # @task
    # def get_caselist_since_date_raw_airflow(
    #     scraper: Any, after_date: datetime, base_path: str
    # ) -> List[Any]:
    #     return get_new_caselist_since_date(
    #         scraper=scraper, after_date=after_date, base_path=base_path
    #     )

    @task
    def process_case_airflow(scraper: Any, case: Any, base_path: str) -> Any:
        return process_case(scraper=scraper, case=case, base_path=base_path)

    # DAG structure
    scraper_name = "{{ params.scraper_name }}"
    scraper_type = get_scraper_type_from_name_default_dummy(scraper_name)
    scraper = scraper_type()
    base_path = generate_intermediate_object_save_path(scraper)
    cases = get_all_caselist_raw_airflow(scraper=scraper, base_path=base_path)
    for case in cases:
        process_case_airflow(scraper=scraper, case=case, base_path=base_path)

    # partial_process_case = partial(
    #     process_case_airflow, scraper=scraper, base_path=base_path
    # )
    # for case in cases:
    #     partial_process_case(case=case)


all_cases_workflow = all_cases_dag()
