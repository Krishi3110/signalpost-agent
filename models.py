from pydantic import BaseModel, HttpUrl, Field
from typing import Dict, Union
from datetime import datetime

class Fact(BaseModel):
    """A single piece of information with its required evidence."""
    value: Union[str, int, float, bool, None]
    source_url: HttpUrl
    fetched_at: datetime

class CompanyProfile(BaseModel):
    """The master template for a company profile."""
    orgnr: str = Field(..., description="The 9-digit Norwegian company number")
    company_name: Fact
    
    # All other facts are stored here, ensuring they follow the Fact schema
    facts: Dict[str, Fact] = Field(default_factory=dict)
