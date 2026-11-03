import datetime
from pydantic import BaseModel
from typing import Optional, List

class Company(BaseModel):
    id: Optional[int] = None
    name: str

class User(BaseModel):
    id: Optional[int] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    company_id: Optional[int] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    nationality: str = "AR"

class Account(BaseModel):
    account_id: str
    status: str
    expiration_date: datetime.datetime
    credits: int
    user_id: Optional[int] = None
    key_type: str = "particulares"
    invoice_number: Optional[str] = None  # 8-digit code — a leading zero is significant
    ticket_type: Optional[str] = None

class AccessLog(BaseModel):
    id: Optional[int] = None
    timestamp: datetime.datetime
    account_id: str
    event_type: str
    reason: Optional[str] = None

# --- Extended schemas ---

class AccountDetail(BaseModel):
    account_id: str
    status: str
    expiration_date: datetime.datetime
    credits: int
    user_id: Optional[int] = None
    key_type: str = "particulares"
    invoice_number: Optional[str] = None  # 8-digit code — a leading zero is significant
    ticket_type: Optional[str] = None

class UserDetail(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str] = None
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    nationality: str = "AR"
    accounts: List[AccountDetail] = []

class AccessLogDetail(BaseModel):
    id: int
    timestamp: datetime.datetime
    account_id: str
    event_type: str
    reason: Optional[str] = None
    user_first_name: Optional[str] = None
    user_last_name: Optional[str] = None
    company_name: Optional[str] = None

class KPIStats(BaseModel):
    today_total: int
    today_grant: int
    today_deny: int
    today_success_rate: float
    last_7_days_total: int
    last_7_days_grant: int
    last_7_days_deny: int
    last_7_days_success_rate: float
    last_30_days_total: int
    last_30_days_grant: int
    last_30_days_deny: int
    last_30_days_success_rate: float
    this_month_total: int
    this_month_grant: int
    this_month_deny: int
    this_month_success_rate: float
    today_deny_not_found: int
    today_deny_expired: int
    today_deny_invalid: int
    today_deny_no_credits: int
