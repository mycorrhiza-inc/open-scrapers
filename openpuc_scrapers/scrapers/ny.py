from openpuc_scrapers.models.attachment import GenericAttachment
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.common.by import By
from pydantic import BaseModel, HttpUrl
from typing import Any, Dict, List, Tuple
import time
from datetime import date, datetime
from bs4 import BeautifulSoup

from openpuc_scrapers.models.case import GenericCase
from openpuc_scrapers.models.filing import GenericFiling
from openpuc_scrapers.scrapers.base import GenericScraper


# document_title: str
# url: HttpUrl
# file_format: str
# document_type: str
# file_name: str
class NYPUCAttachment(BaseModel):
    name: str = ""
    url: str = ""
    file_name: str = ""

    # case_number
    # date_filed
    # filing_on_behalf_of
    # description_of_filing
    # filing_no
    # filed_by
    # response_to


class NYPUCFiling(BaseModel):
    attachements: List[NYPUCAttachment] = []
    serial: str = ""
    date_filed: str = ""
    nypuc_doctype: str = ""
    name: str = ""
    organization: str = ""
    itemNo: str = ""
    docket_id: str = ""


# organization: str (though maybe it should be OrganizationNY)?
# matter_type: str
# matter_subtype: str
# case_title: str
# related_cases: list[DocketNY]
# party_list: list[OrganizationNY] (or list[PartyNY]]?
# calendar: list[EventNY]?
class NYPUCDocket(BaseModel):
    docket_id: str  # 24-C-0663
    matter_type: str  # Complaint
    matter_subtype: str  # Appeal of an Informal Hearing Decision
    title: str  # In the Matter of the Rules and Regulations of the Public Service
    organization: str  # Individual
    date_filed: str
    industry_affected: str


def combine_dockets(docket_lists: List[List[NYPUCDocket]]) -> List[NYPUCDocket]:
    """Combine and sort dockets from all industries"""
    all_dockets = [d for sublist in docket_lists for d in sublist]
    return sorted(
        all_dockets,
        key=lambda x: datetime.strptime(x.date_filed, "%m/%d/%Y"),
        reverse=True,
    )


def process_docket(docket: NYPUCDocket) -> str:
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
        return table_element.get_attribute("outerHTML")

    except Exception as e:
        print(f"Error processing docket {docket.docket_id}: {e}")
        raise e
    finally:
        driver.quit()


def extract_docket_info(intermediate: Dict[str, Any]) -> List[NYPUCDocket]:
    """
    Extract complete docket information from HTML table rows

    Args:
        html_content (str): HTML string containing the table

    Returns:
        List[NYPUCDocket]: List of NYPUCDocket objects containing details for each docket
    """
    html_content = intermediate["html"]
    soup = BeautifulSoup(html_content, "html.parser")
    rows = soup.find_all("tr", role="row")

    docket_infos: List[NYPUCDocket] = []

    for row in rows:
        # Get all cells in the row
        cells = row.find_all("td")
        if len(cells) >= 6:  # Ensure we have all required cells
            try:
                docket_info = NYPUCDocket(
                    docket_id=cells[0].find("a").text.strip(),
                    matter_type=cells[1].text.strip(),
                    matter_subtype=cells[2].text.strip(),
                    date_filed=cells[3].text.strip(),
                    title=cells[4].text.strip(),
                    organization=cells[5].text.strip(),
                    industry_affected=intermediate["industry"].strip(),
                )
                docket_infos.append(docket_info)
            except Exception as e:
                # Skip malformed rows
                print(f"Error processing row: {e}")
                continue

    return docket_infos


def extract_rows(table_html: str, case: str) -> List[NYPUCFiling]:
    """Parse table HTML with BeautifulSoup and extract filing data."""
    soup = BeautifulSoup(table_html, "html.parser")
    table = soup.find("table", id="tblPubDoc")

    if not table:
        return []

    body = table.find("tbody")
    rows = body.find_all("tr") if body else []
    filing_data = []

    for row in rows:
        try:
            cells = row.find_all("td")
            if len(cells) < 7:
                continue  # Skip rows with insufficient cells

            link = cells[3].find("a")
            if not link:
                continue  # Skip rows without links

            filing_item = NYPUCFiling(
                attachment=NYPUCAttachment(
                    name=link.get_text(strip=True),
                    url=link["href"],
                    file_name=cells[6].get_text(strip=True),
                ),
                serial=cells[0].get_text(strip=True),
                date_filed=cells[1].get_text(strip=True),
                nypuc_doctype=cells[2].get_text(strip=True),
                docket_id=case,
                organization=cells[4].get_text(strip=True),
                itemNo=cells[5].get_text(strip=True),
            )
            filing_data.append(filing_item)
        except Exception as e:
            print(f"Error processing row: {e}\nRow content: {row.prettify()}")

    deduped_data = deduplicate_individual_attachments_into_files(filing_data)
    return deduped_data


def deduplicate_individual_attachments_into_files(
    raw_files: List[NYPUCFiling],
) -> List[NYPUCFiling]:
    dict_nypuc = {}

    def make_dedupe_string(file: NYPUCFiling) -> str:
        return f"itemnum-{file.itemNo}-caseid-{file.docket_id}"

    for file in raw_files:
        dedupestr = make_dedupe_string(file)
        if dict_nypuc.get(dedupestr) is not None:
            dict_nypuc[dedupestr].attachements.append(file.attachements)
    return_vals = dict_nypuc.values()
    return list(return_vals)


class NYPUCScraper(GenericScraper[NYPUCDocket, NYPUCFiling]):
    """Concrete implementation of GenericScraper for NYPUC"""

    def universal_caselist_intermediate(self) -> Dict[str, Any]:
        """Return industry numbers to process"""

        def process_industry(industry_num: int) -> Dict[str, Any]:
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
                industry_affected = industry_elem.text.replace(
                    "Industry Affected:", ""
                ).strip()
                time.sleep(2)  # Reduced from 30 for demonstration

                table_elem = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "#tblSearchedMatterExternal > tbody")
                    )
                )
                table_html = table_elem.get_attribute("outerHTML") or ""

                # Use existing helper function
                return {"html": table_html, "industry": industry_affected}

            except TimeoutException as e:
                print(f"Timeout waiting for industry {industry_num}")
                raise e
            except Exception as e:
                print(f"Error processing industry {industry_num}: {e}")
                raise e
            finally:
                driver.quit()

        nums = list(range(1, 21))  # Example range of industry numbers
        docket_intermediate_lists = [
            process_industry(industry_num) for industry_num in nums
        ]
        return {"industry_intermediates": docket_intermediate_lists}

    def universal_caselist_from_intermediate(
        self, intermediate: Dict[str, Any]
    ) -> List[NYPUCDocket]:
        intermediate_list = intermediate["industry_intermediates"]
        caselist: List[NYPUCDocket] = []
        for industry_intermediate in intermediate_list:
            docket_info = extract_docket_info(industry_intermediate)
            caselist.extend(docket_info)
        return caselist

    def filing_data_intermediate(self, data: NYPUCDocket) -> Dict[str, Any]:
        """Get HTML content for a docket's filings"""
        return {"docket_id": data.docket_id, "html": process_docket(data)}

    def filing_data_from_intermediate(
        self, intermediate: Dict[str, Any]
    ) -> List[NYPUCFiling]:
        """Convert docket HTML to filing data"""
        docket_id, html = intermediate
        return extract_rows(html, docket_id)

    def updated_cases_since_date_intermediate(self, after_date: date) -> Dict[str, Any]:
        raise Exception("Not Impelemented")

    def updated_cases_since_date_from_intermediate(
        self, intermediate: Dict[str, Any], after_date: date
    ) -> List[NYPUCDocket]:
        raise Exception("Not Impelemented")

    def into_generic_case_data(self, state_data: NYPUCDocket) -> GenericCase:
        """Convert to generic case format"""
        return GenericCase(
            case_number=state_data.docket_id,
            case_type=f"{state_data.matter_type} - {state_data.matter_subtype}",
            description=state_data.title,
            industry=state_data.industry_affected,
            petitioner=state_data.organization,
            opened_date=datetime.strptime(state_data.date_filed, "%m/%d/%Y").date(),
            extra_metadata={
                "matter_type": state_data.matter_type,
                "matter_subtype": state_data.matter_subtype,
            },
        )

    def into_generic_filing_data(self, state_data: NYPUCFiling) -> GenericFiling:
        """Convert NYPUCFiling to a generic Filing object."""

        filed_date_obj = datetime.strptime(state_data.date_filed, "%m/%d/%Y").date()

        attachments = [
            GenericAttachment(name=att.name, url=HttpUrl(att.url))
            for att in state_data.attachements
        ]

        return GenericFiling(
            # case_number=self.docket_id,
            filed_date=filed_date_obj,
            party_name=state_data.organization,
            filing_type=state_data.nypuc_doctype,
            description=state_data.name,
            attachments=attachments,
            extra_metadata={},
        )
