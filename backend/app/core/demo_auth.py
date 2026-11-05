from typing import Literal

from pydantic import BaseModel

Role = str
DemoUserId = Literal[
    "demo-employee",
    "demo-hr",
    "demo-recruiter",
    "demo-it",
    "demo-security",
    "demo-manager",
    "demo-admin",
]


class DemoUser(BaseModel):
    user_id: str
    display_name: str
    role: Role
    capabilities: list[str]


DEMO_USERS: dict[DemoUserId, DemoUser] = {
    "demo-employee": DemoUser(
        user_id="demo-employee",
        display_name="Alex Employee",
        role="employee",
        capabilities=["chat:ask", "knowledge:read:general"],
    ),
    "demo-hr": DemoUser(
        user_id="demo-hr",
        display_name="Riley HR",
        role="hr_user",
        capabilities=["chat:ask", "knowledge:read:general", "knowledge:read:hr"],
    ),
    "demo-recruiter": DemoUser(
        user_id="demo-recruiter",
        display_name="Sam Recruiter",
        role="recruiter",
        capabilities=[
            "chat:ask",
            "knowledge:read:general",
            "recruitment:read",
        ],
    ),
    "demo-it": DemoUser(
        user_id="demo-it",
        display_name="Jordan IT",
        role="it_support",
        capabilities=[
            "chat:ask",
            "knowledge:read:general",
            "knowledge:read:it",
            "jira:read",
            "jira:propose",
        ],
    ),
    "demo-security": DemoUser(
        user_id="demo-security",
        display_name="Casey Security",
        role="security_analyst",
        capabilities=["chat:ask", "threat_scans:scan"],
    ),
    "demo-manager": DemoUser(
        user_id="demo-manager",
        display_name="Morgan Team Manager",
        role="team_manager",
        capabilities=[
            "chat:ask",
            "knowledge:read:general",
            "jira:read",
            "jira:approve",
        ],
    ),
    "demo-admin": DemoUser(
        user_id="demo-admin",
        display_name="Taylor Administrator",
        role="administrator",
        capabilities=["system:admin", "audit:read", "knowledge:manage"],
    ),
}
