import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.app.connectors.base import ConnectorMetadata

CAMPAIGNS_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
    / "recruitment_campaigns"
    / "campaigns.json"
)


class CandidateProfile(BaseModel):
    document_id: str
    profile_id: str
    years_experience: int = Field(ge=0)
    skills: list[str]
    evidence: str


class Campaign(BaseModel):
    campaign_id: str
    title: str
    minimum_years_experience: int = Field(ge=0)
    required_skills: list[str]
    candidates: list[CandidateProfile]


class SuccessFeeTerms(BaseModel):
    rate_percent: Decimal = Field(gt=0, le=100)
    currency: str
    basis: str
    agreement_document_id: str


class RecruitmentDataset(BaseModel):
    campaigns: list[Campaign]
    success_fee: SuccessFeeTerms


class CandidateMatch(BaseModel):
    profile_id: str
    document_id: str
    matched: bool
    years_experience: int
    minimum_years_experience: int
    matched_skills: list[str]
    missing_skills: list[str]
    evidence: str


class CVMatchResult(BaseModel):
    campaign_id: str
    campaign_title: str
    connector: str = "fictional_recruitment_demo"
    status: str = "mock"
    matched_count: int
    total_candidates: int
    criteria: list[str]
    matches: list[CandidateMatch]
    human_review_required: bool = True


class SuccessFeeResult(BaseModel):
    connector: str = "fictional_recruitment_demo"
    status: str = "mock"
    rate_percent: Decimal
    salary_basis: str
    currency: str
    salary: Decimal | None
    fee: Decimal | None
    formula: str
    agreement_document_id: str


class RecruitmentDemoConnector:
    metadata = ConnectorMetadata(connector="fictional_recruitment_demo")

    def __init__(self, dataset_path: Path = CAMPAIGNS_PATH) -> None:
        try:
            payload: Any = json.loads(dataset_path.read_text(encoding="utf-8"))
            self._dataset = RecruitmentDataset.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise ValueError(f"Invalid fictional recruitment fixture: {dataset_path}") from error

    def match_campaign(self, campaign_id: str) -> CVMatchResult | None:
        campaign = next(
            (item for item in self._dataset.campaigns if item.campaign_id == campaign_id),
            None,
        )
        if campaign is None:
            return None

        required_skills = {skill.casefold() for skill in campaign.required_skills}
        results: list[CandidateMatch] = []
        for candidate in campaign.candidates:
            candidate_skills = {skill.casefold() for skill in candidate.skills}
            matched_skills = [
                skill
                for skill in campaign.required_skills
                if skill.casefold() in candidate_skills
            ]
            missing_skills = [
                skill
                for skill in campaign.required_skills
                if skill.casefold() not in candidate_skills
            ]
            meets_experience = (
                candidate.years_experience >= campaign.minimum_years_experience
            )
            results.append(
                CandidateMatch(
                    profile_id=candidate.profile_id,
                    document_id=candidate.document_id,
                    matched=meets_experience and not (required_skills - candidate_skills),
                    years_experience=candidate.years_experience,
                    minimum_years_experience=campaign.minimum_years_experience,
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    evidence=candidate.evidence,
                )
            )

        return CVMatchResult(
            campaign_id=campaign.campaign_id,
            campaign_title=campaign.title,
            matched_count=sum(result.matched for result in results),
            total_candidates=len(results),
            criteria=[
                f"At least {campaign.minimum_years_experience} years of experience",
                *(f"Skill: {skill}" for skill in campaign.required_skills),
            ],
            matches=results,
        )

    def calculate_success_fee(self, salary: Decimal | None) -> SuccessFeeResult:
        terms = self._dataset.success_fee
        fee: Decimal | None = None
        if salary is not None:
            try:
                salary = Decimal(salary)
            except InvalidOperation as error:
                raise ValueError("Salary must be a valid decimal amount.") from error
            if not salary.is_finite() or salary <= 0 or salary > Decimal("1000000000"):
                raise ValueError("Salary must be greater than zero and no more than 1,000,000,000.")
            fee = (salary * terms.rate_percent / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        return SuccessFeeResult(
            rate_percent=terms.rate_percent,
            salary_basis=terms.basis,
            currency=terms.currency,
            salary=salary,
            fee=fee,
            formula="salary × rate_percent ÷ 100",
            agreement_document_id=terms.agreement_document_id,
        )
