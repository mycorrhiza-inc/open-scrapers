from flytekit import task, workflow, map_task
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.common.by import By
from pydantic import BaseModel
from typing import List, Union
import time
from datetime import datetime
from bs4 import BeautifulSoup
import pathlib

# ... Keep the Pydantic models (NYPUCFileData and NYPUCDocketInfo) unchanged ...


class NYPUCFileData(BaseModel):
    serial: str
    date_filed: str
    nypuc_doctype: str
    name: str
    url: str
    organization: str
    itemNo: str
    file_name: str
    docket_id: str

    def __str__(self):
        return f"\n(\n\tSerial: {self.serial}\n\tDate Filed: {self.date_filed}\
        \n\tNY PUC Doc Type: {self.nypuc_doctype}\n\tName: {self.name}\n\tURL: \
        {self.url}\nOrganization: {self.organization}\n\tItem No: {self.itemNo}\n\
        \tFile Name: {self.file_name}\n)\n"

    def __repr__(self):
        return self.__str__()


class NYPUCDocketInfo(BaseModel):
    docket_id: str  # 24-C-0663
    matter_type: str  # Complaint
    matter_subtype: str  # Appeal of an Informal Hearing Decision
    title: str  # In the Matter of the Rules and Regulations of the Public Service
    organization: str  # Individual
    date_filed: str
    industry_affected: str


@task
def process_industry(industry_num: int) -> List[NYPUCDocketInfo]:
    """Task to process a single industry number and return its dockets"""
    driver = webdriver.Chrome()
    all_dockets = []

    try:
        url = f"https://documents.dps.ny.gov/public/Common/SearchResults.aspx?MC=1&IA={industry_num}"
        driver.get(url)

        wait = WebDriverWait(driver, 300)
        industry_elem = wait.until(
            EC.presence_of_element_located(
                (By.ID, "GridPlaceHolder_lblSearchCriteriaValue")
            )
        )
        industry_affected = industry_elem.text.replace("Industry Affected:", "").strip()
        time.sleep(2)  # Reduced from 30 for demonstration

        table_elem = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#tblSearchedMatterExternal > tbody")
            )
        )
        table_html = table_elem.get_attribute("outerHTML") or ""

        # Use existing helper function
        return extract_docket_info(table_html, industry_affected)

    except TimeoutException:
        print(f"Timeout waiting for industry {industry_num}")
        return []
    except Exception as e:
        print(f"Error processing industry {industry_num}: {e}")
        return []
    finally:
        driver.quit()


@task
def combine_dockets(docket_lists: List[List[NYPUCDocketInfo]]) -> List[NYPUCDocketInfo]:
    """Combine and sort dockets from all industries"""
    all_dockets = [d for sublist in docket_lists for d in sublist]
    return sorted(
        all_dockets,
        key=lambda x: datetime.strptime(x.date_filed, "%m/%d/%Y"),
        reverse=True,
    )


@task
def process_docket(docket: NYPUCDocketInfo) -> List[NYPUCFileData]:
    """Task to process a single docket and return its files"""
    driver = webdriver.Chrome()
    try:
        url = f"https://documents.dps.ny.gov/public/MatterManagement/CaseMaster.aspx?MatterCaseNo={docket.docket_id}"
        driver.get(url)

        # Custom wait logic
        for _ in range(10):  # Reduced from 60 for demonstration
            overlay = driver.find_element(By.ID, "GridPlaceHolder_upUpdatePanelGrd")
            if overlay.get_attribute("style") == "display: none;":
                break
            time.sleep(1)
        else:
            raise TimeoutError("Page load timed out")

        table_element = driver.find_element(By.ID, "tblPubDoc")
        return extract_rows(table_element.get_attribute("outerHTML"), docket.docket_id)

    except Exception as e:
        print(f"Error processing docket {docket.docket_id}: {e}")
        raise e
        return []
    finally:
        driver.quit()


@workflow
def full_scraping_workflow() -> List[List[NYPUCFileData]]:
    """Main workflow that coordinates all scraping tasks"""
    # Process all industries in parallel
    industries = list(range(1, 11))
    industry_results = process_industry.map(industry_num=industries)

    # Combine results from all industries
    combined_dockets = combine_dockets(docket_lists=industry_results)

    # Process all dockets in parallel
    return process_docket.map(docket=combined_dockets)


if __name__ == "__main__":
    # For local testing
    print("Running scraping workflow...")
    results = full_scraping_workflow()
    print(f"Scraped {len(results)} dockets with files")
