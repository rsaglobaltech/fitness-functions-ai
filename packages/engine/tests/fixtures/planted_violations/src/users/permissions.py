"""Two more high-complexity functions."""


def can_perform(
    role: str,
    resource: str,
    owns: bool,
    in_team: bool,
    is_admin: bool,
    is_super: bool,
) -> bool:
    if is_super:
        return True
    if is_admin and resource != "billing":
        return True
    if role == "owner" and owns:
        return True
    if role == "owner" and in_team:
        return True
    if role == "manager" and resource == "team":
        return True
    if role == "manager" and resource == "report":
        return True
    if role == "member" and resource == "task" and owns:
        return True
    if role == "viewer" and resource == "task":
        return True
    if role == "viewer" and resource == "report" and in_team:
        return True
    if role == "guest" and resource == "public":
        return True
    return False


def score_request(
    method: str,
    path: str,
    auth: bool,
    rate_limited: bool,
    user_agent: str,
) -> int:
    score = 0
    if method == "GET":
        score += 1
    elif method == "POST":
        score += 2
    elif method == "PUT":
        score += 3
    elif method == "DELETE":
        score += 5
    if path.startswith("/admin"):
        score += 10
    elif path.startswith("/api"):
        score += 5
    elif path.startswith("/public"):
        score += 1
    if not auth:
        score += 20
    if rate_limited:
        score += 30
    if "bot" in user_agent.lower():
        score += 15
    if "scraper" in user_agent.lower():
        score += 25
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score
